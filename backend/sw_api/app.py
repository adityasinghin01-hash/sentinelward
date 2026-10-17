"""App lifecycle, dependency injection, the core REST routes and the real WebSocket endpoint.

The remaining routes live in routes/ and share the same auth dependencies."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
import logging
from pathlib import Path

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from sw_common import Bus

from . import commands, presenters
from .auth import COOKIE_NAME, ROLE_FRONTEND, Sessions, check_origin
from .config import Clock, Settings, UserConfig, load_users, load_ward
from .ingest import Ingest
from .models import (Acknowledge, ActionsResponse, Bedside, DemoReceipt, DemoRun, DeviceEntry, Escalate,
                     HealthResponse, Isolate, Receipt, SessionInput, SessionResponse, Undo, WardResponse)
from .routes import Deps, clinical, records, security
from .state import WardState
from .store import MemoryStore, Store
from .ws import Hub

LOG = logging.getLogger(__name__)


class Runtime:
    """All mutable clinical state belongs to the application's asyncio loop."""

    def __init__(self, settings: Settings, bus, store: Store | None, clock: Clock):
        self.settings, self.bus, self.clock = settings, bus, clock
        users = load_users(settings.users_yaml)
        self.state = WardState(load_ward(settings.ward_yaml, users), clock)
        if store is None:
            if settings.use_memory_store:
                store = MemoryStore()
            else:
                from .postgres import PostgresStore
                store = PostgresStore(settings.pg_dsn, self.state.ward, settings.schema_sql, clock)
        self.store = store
        self._lookup_tasks: set[asyncio.Task] = set()
        self.sessions = Sessions(users, settings, clock)
        self.hub = Hub(clock)
        self.ingest = Ingest(self)
        self._feed_connected: bool | None = None

    def resolve_pins(self) -> None:
        """Answer "newest trusted point before the cutoff" lookups RAM could not (never waits for SQL)."""
        lookups = self.state.take_pin_lookups()
        if not lookups:
            return
        if self.store.sync_lookups:
            for bed_id, cutoff, inclusive in lookups:
                self.state.set_pin(bed_id, cutoff, inclusive, self.store.trusted_point(bed_id, cutoff, inclusive))
            return
        for lookup in lookups:
            task = asyncio.get_running_loop().create_task(self._lookup(*lookup))
            self._lookup_tasks.add(task)
            task.add_done_callback(self._lookup_tasks.discard)

    async def _lookup(self, bed_id: str, cutoff: int, inclusive: bool) -> None:
        generation = self.ingest.generation
        try:
            point = await self.store.trusted_point_async(bed_id, cutoff, inclusive)
        except Exception:  # noqa: BLE001 - database down: show untrusted last values, retry later
            LOG.exception("trusted-point lookup failed for %s", bed_id)
            if generation != self.ingest.generation:
                return
            self.state._lookups_in_flight.discard((bed_id, cutoff, inclusive))
            return
        if generation != self.ingest.generation:
            return
        self.state.set_pin(bed_id, cutoff, inclusive, point)
        self.push_bed(bed_id)

    async def resolve_pins_now(self) -> None:
        """Like resolve_pins, but wait for the database answers (used by reads)."""
        if self.store.sync_lookups:
            self.resolve_pins()
            return
        for lookup in self.state.take_pin_lookups():
            await self._lookup(*lookup)
        if self._lookup_tasks:  # lookups already started by ingest: wait briefly for their answers
            await asyncio.wait(list(self._lookup_tasks), timeout=0.5)

    def push_bed(self, bed_id: str, critical: bool = True) -> None:
        """Send the bed's current payload to every WebSocket client."""
        presenters.bed(self.state, bed_id)  # registers any pin lookup this view needs
        self.resolve_pins()
        payload = presenters.bed(self.state, bed_id)
        self.hub.broadcast({"type": "bed.updated", "payload": payload}, critical)

    def publish_pending(self) -> None:
        for publication_id, message in self.store.pending_publications():
            if not self.bus.is_connected:
                break
            try:
                accepted = self.bus.publish(message)
            except Exception:
                LOG.exception("Publication retained for retry: %s", publication_id)
                break
            if not accepted:
                break  # Preserve outbox order across reconnects.
            self.store.published(publication_id)

    async def tick(self) -> None:
        for change in self.state.changes():
            self.push_bed(change["bed_id"])
        self.resolve_pins()
        self.hub.flush()
        connected = self.bus.is_connected
        if connected != self._feed_connected:
            self._feed_connected = connected
            self.hub.broadcast({"type": "connection.changed", "payload": {"state": "live" if connected else "disconnected", "occurred_at": self.clock.ms()}})
        self.publish_pending()
        self.sessions.expire()

    def reset(self) -> None:
        self.ingest.reset()
        for lookup in list(self._lookup_tasks):
            lookup.cancel()
        self.store.reset()
        self.state.reset()
        for bed_id in self.state.beds:
            self.push_bed(bed_id)

    def health(self) -> dict:
        stats = self.bus.stats()
        db_ok = self.store.db_ok
        writer = getattr(self.store, "writer", None)
        return {"ok": self.bus.is_connected and (db_ok or not self.store.durable),
                "mqtt_connected": self.bus.is_connected, "db_ok": db_ok,
                "storage": self.store.storage, "durable": self.store.durable,
                "db_queued_rows": writer.queued if writer is not None else 0,
                "beds_online": self.state.beds_online(),
                "last_message_ts": self.state.last_message_ms,
                "invalid_messages": self.ingest.invalid + stats.get("invalid", 0),
                "pending_publications": len(self.store.pending_publications())}


def create_app(*, settings: Settings | None = None, bus=None, store: Store | None = None, clock: Clock | None = None) -> FastAPI:
    """Build an injectable app; external connections start only during lifespan."""
    settings = settings or Settings.from_env()
    clock = clock or Clock()
    bus = bus if bus is not None else Bus(settings.mqtt_host, settings.mqtt_port, "sw-api", username=settings.mqtt_user, password=settings.mqtt_pass)
    runtime = Runtime(settings, bus, store, clock)

    @asynccontextmanager
    async def lifespan(app):
        warm = await runtime.store.start()
        if warm is not None:
            runtime.state.warm_start(warm)
            runtime.ingest.reset_at = warm.reset_at
            LOG.info("warm start: %d beds with data, %d actions, %d records", len(warm.vitals),
                     len(warm.actions), len(warm.records))
        runtime.ingest.start()
        async def ticker():
            while True:
                await runtime.tick()
                await asyncio.sleep(.1)
        task = asyncio.create_task(ticker())
        try:
            yield
        finally:
            runtime.publish_pending()
            # Stop MQTT callbacks first; drain already-scheduled callbacks before final publications.
            await asyncio.to_thread(bus.close)
            runtime.ingest.accepting = False
            await asyncio.sleep(0)
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            runtime.publish_pending()
            for lookup in list(runtime._lookup_tasks):
                lookup.cancel()
            await asyncio.gather(*runtime._lookup_tasks, return_exceptions=True)
            pending = len(runtime.store.pending_publications())
            if pending:
                LOG.warning("%d publications unsent at shutdown (%s)", pending,
                            "kept in the database outbox" if runtime.store.durable else "lost: memory store")
            await runtime.store.close()

    app = FastAPI(title="SentinelWard API", version="1.2.0", lifespan=lifespan,
                  description="REST + /ws for the SentinelWard screens. See API.md for examples.")
    app.state.runtime = runtime

    @app.middleware("http")
    async def same_origin(request: Request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            try:
                check_origin(request)
            except HTTPException as exc:
                return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        return await call_next(request)

    async def user(request: Request) -> UserConfig:
        return runtime.sessions.authenticate(request)

    def roles(*allowed: str):
        async def authorize(identity: UserConfig = Depends(user)) -> UserConfig:
            if identity.role not in allowed:
                raise HTTPException(403, "Role is not allowed for this operation")
            return identity
        return authorize

    def require_bed(bed_id: str) -> None:
        if bed_id not in runtime.state.beds:
            raise HTTPException(404, "Bed not found")

    @app.post("/api/session", response_model=SessionResponse)
    async def session(body: SessionInput, response: Response, request: Request):
        token, identity = runtime.sessions.create(body)
        response.set_cookie(COOKIE_NAME, token, max_age=settings.session_ttl_s, httponly=True, samesite="lax", secure=request.url.scheme == "https", path="/")
        response.headers["Cache-Control"] = "no-store"
        return {"token": token, "role": ROLE_FRONTEND.get(identity.role, identity.role), "name": identity.display_name, "display_name": identity.display_name}

    @app.get("/api/health", response_model=HealthResponse)
    async def health():
        return runtime.health()

    @app.get("/api/ward", response_model=WardResponse, response_model_exclude_unset=True)
    async def ward(identity=Depends(user)):
        presenters.ward(runtime.state)
        await runtime.resolve_pins_now()
        return presenters.ward(runtime.state)

    @app.get("/api/ward/preview", response_model=WardResponse, response_model_exclude_unset=True)
    async def preview():
        presenters.ward(runtime.state, preview=True)
        await runtime.resolve_pins_now()
        return presenters.ward(runtime.state, preview=True)

    @app.get("/api/devices", response_model=list[DeviceEntry])
    async def devices(identity=Depends(user)):
        return presenters.devices(runtime.state)

    @app.get("/api/actions", response_model=ActionsResponse)
    async def actions(limit: int = Query(default=200, ge=1, le=5000), identity=Depends(user)):
        return presenters.action_log(list(runtime.store.actions.values()), limit)

    @app.post("/api/beds/{bed_id}/acknowledge", status_code=202, response_model=Receipt, response_model_exclude_none=True)
    async def acknowledge(bed_id: str, body: Acknowledge = Body(default_factory=Acknowledge), identity=Depends(roles("nurse", "doctor"))):
        require_bed(bed_id)
        commands.agree(body.bedId, bed_id, "bedId")
        alert = runtime.state.alert_to_ack(bed_id)
        if alert is None:
            raise HTTPException(409, "No open alert for this bed")
        return commands.request(runtime, identity, "ack_alert", alert["alert_id"], bed_id, body.notes)

    @app.post("/api/beds/{bed_id}/bedside-check", status_code=201, response_model=Receipt, response_model_exclude_none=True)
    async def bedside_check(bed_id: str, body: Bedside, identity=Depends(roles("nurse", "doctor"))):
        require_bed(bed_id)
        commands.agree(body.bedId, bed_id, "bedId")
        return commands.bedside(runtime, identity, bed_id, body.status or body.result, body.notes)

    @app.post("/api/alerts/{alert_id}/escalate", status_code=202, response_model=Receipt, response_model_exclude_none=True)
    async def escalate(alert_id: str, body: Escalate = Body(default_factory=Escalate), identity=Depends(roles("nurse", "doctor"))):
        alert = runtime.state.alerts.get(alert_id) or runtime.store.alerts.get(alert_id)
        if alert is None:
            raise HTTPException(404, "Alert not found")
        if alert["status"] not in ("open", "escalated"):
            raise HTTPException(409, "Alert is no longer open")
        commands.agree(body.alertId, alert_id, "alertId")
        commands.agree(body.bedId, alert["bed_id"], "bedId")
        return commands.request(runtime, identity, "escalate_alert", alert_id, alert["bed_id"], body.notes)

    @app.post("/api/devices/{device_id}/isolate", status_code=202, response_model=Receipt, response_model_exclude_none=True)
    async def isolate(device_id: str, body: Isolate = Body(default_factory=Isolate), identity=Depends(roles("it", "admin"))):
        device = runtime.state.devices.get(device_id)
        if device is None:
            raise HTTPException(404, "Device not found")
        commands.agree(body.deviceId, device_id, "deviceId")
        commands.agree(body.bedId, device.bed_id, "bedId")
        return commands.request(runtime, identity, "isolate_device", device_id, device.bed_id, body.notes)

    @app.post("/api/actions/{action_id}/undo", status_code=202, response_model=Receipt, response_model_exclude_none=True)
    async def undo(action_id: str, body: Undo = Body(default_factory=Undo), identity=Depends(roles("it", "admin"))):
        action = runtime.store.actions.get(action_id) or runtime.state.actions.get(action_id)
        if action is None:
            raise HTTPException(404, "Action not found")
        if not presenters.undoable(action, list(runtime.store.actions.values())):
            raise HTTPException(409, "Action cannot be undone")
        bed_id = action.get("bed_id")
        if bed_id is None and action.get("device_id") in runtime.state.devices:
            bed_id = runtime.state.devices[action["device_id"]].bed_id
        commands.agree(body.originalActionId, action_id, "originalActionId")
        commands.agree(body.bedId, bed_id, "bedId")
        return commands.request(runtime, identity, "undo_action", action_id, bed_id, body.notes)

    @app.post("/api/demo/run", status_code=202, response_model=DemoReceipt, response_model_exclude_none=True)
    async def run_demo(body: DemoRun = Body(default_factory=DemoRun), identity=Depends(roles("admin"))):
        return commands.demo(runtime, "run", body.scenario, body.speed, body.start_at_s)

    @app.post("/api/demo/reset", status_code=202, response_model=DemoReceipt, response_model_exclude_none=True)
    async def reset_demo(identity=Depends(roles("admin"))):
        return commands.demo(runtime, "reset")

    @app.websocket("/ws")
    async def websocket(websocket: WebSocket):
        try:
            check_origin(websocket)
            runtime.sessions.authenticate(websocket)
        except HTTPException:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        presenters.ward(runtime.state)
        await runtime.resolve_pins_now()
        client = runtime.hub.subscribe(presenters.ward(runtime.state)["beds"])
        async def send():
            while True:
                message = await client.get()
                if message is None:
                    await websocket.close(code=1013)
                    return
                await websocket.send_json(message)
        async def receive():
            while True:
                try:
                    event = await asyncio.wait_for(websocket.receive(), 1.0)
                    if event["type"] == "websocket.disconnect":
                        return
                except asyncio.TimeoutError:
                    pass
                try:
                    runtime.sessions.authenticate(websocket)
                except HTTPException:
                    await websocket.close(code=1008)
                    return
        tasks = [asyncio.create_task(send()), asyncio.create_task(receive())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for completed in done:
                completed.result()
        except (WebSocketDisconnect, RuntimeError, OSError):
            pass
        finally:
            runtime.hub.unsubscribe(client)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    deps = Deps(runtime=runtime, user=user, roles=roles, require_bed=require_bed)
    clinical.register(app, deps)
    security.register(app, deps)
    records.register(app, deps)

    # Last route: serve a prebuilt SPA on the same origin, preserving API 404s.
    if settings.frontend_dist.is_dir() and (settings.frontend_dist / "index.html").is_file():
        root = settings.frontend_dist.resolve()
        @app.get("/{path:path}", include_in_schema=False)
        async def frontend(path: str):
            if path == "api" or path.startswith("api/") or path == "ws":
                raise HTTPException(404, "Not found")
            target = (root / path).resolve()
            if not target.is_relative_to(root):
                raise HTTPException(404, "Not found")
            if target.is_file():
                return FileResponse(target)
            if path.startswith("assets/") or Path(path).suffix:
                raise HTTPException(404, "Not found")
            return FileResponse(root / "index.html")
    return app
