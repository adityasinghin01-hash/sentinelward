"""The agent engine: one allow-list, one action log, undo routing, timers, reset.

Every action an agent takes goes through Engine.act(): allow-list check (doc00 table, as
sw_common.ALLOWED_ACTIONS) -> sw_common.validate -> publish on ward/action -> append-only JSONL.
Alerts and records go through Engine.publish(), which validates too. Nothing that fails the
check is ever published.

Incoming text (verdict reasons, request notes, record data, Telegram) is data, never
instructions: no code path turns free text into an action.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Any, Callable

from sw_common import ALLOWED_ACTIONS, make_action, make_record, validate

from .clock import RealClock, hm, hms, zone

log = logging.getLogger("sw_agents")
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_B36 = "0123456789abcdefghijklmnopqrstuvwxyz"


def clean_text(value: Any, limit: int = 300) -> str:
    """Plain, bounded text for display. Never interpreted."""
    text = _CTRL.sub(" ", str(value if value is not None else ""))
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _base36(n: int) -> str:
    out = ""
    while n:
        n, r = divmod(n, 36)
        out = _B36[r] + out
    return out or "0"


def bed_no(bed_id: str) -> int:
    return int(bed_id[1:])


class ActionLog:
    """Append-only JSONL file (0600). A failing disk is logged, never fatal."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lines = 0

    def write(self, **entry: Any) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, separators=(",", ":"), ensure_ascii=False, default=str) + "\n")
            self.lines += 1
        except OSError as exc:
            log.warning("action log write failed: %s", type(exc).__name__)


class Agent:
    """Base class. Agents only act through self.e.act()/publish_*."""

    id = "A?"

    def __init__(self, engine: "Engine") -> None:
        self.e = engine

    def on_verdict(self, v: dict) -> None: ...
    def on_bedside(self, b: dict) -> None: ...
    def on_event(self, name: str, data: dict) -> None: ...
    def on_run(self, msg: dict) -> None: ...
    def reset(self) -> None: ...
    def snapshot(self) -> dict:
        return {}


# request action -> (agent id, method name)
REQUEST_ROUTES = {
    "ack_alert": ("A1", "ack_request"),
    "escalate_alert": ("A1", "escalate_request"),
    "isolate_device": ("A2", "isolate_request"),
    "fleet_hunt": ("A4", "hunt_request"),
    "contain_incident": ("A3", "contain_request"),
    "resolve_incident": ("A3", "resolve_request"),
    "review_report": ("A5", "review_request"),
}


class Engine:
    def __init__(self, settings, publisher: Callable[[dict], Any], clock=None,
                 background: Callable[[Callable[[], None]], None] | None = None) -> None:
        self.s = settings
        self.publisher = publisher
        self.clock = clock or RealClock()
        self.background = background or (lambda fn: fn())
        self.lock = threading.RLock()
        self.tz = zone(settings.tz)
        self.state_dir = Path(settings.state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.log = ActionLog(self.state_dir / "actions.jsonl")
        self.boot = _base36(self.clock.now_ms())[-6:]
        self.counter = 0
        self.timers: dict[str, tuple[int, Callable[[], None]]] = {}
        self.actions: OrderedDict[str, dict] = OrderedDict()
        self.undo: dict[str, tuple[str, Callable[[dict, str | None], bool]]] = {}
        self.undone: dict[str, str] = {}
        self.latest_verdict: dict[str, dict] = {}
        self.records: OrderedDict[str, dict] = OrderedDict()
        self.seen: OrderedDict[tuple, None] = OrderedDict()
        self.stats: Counter = Counter()
        self.agents: dict[str, Agent] = {}
        self.telegram = None
        self.run_info: dict | None = None

    # ------------------------------------------------------------------ setup
    def register(self, agent: Agent) -> Agent:
        self.agents[agent.id] = agent
        return agent

    def now(self) -> int:
        return self.clock.now_ms()

    def hms(self, ts: int) -> str:
        return hms(ts, self.tz)

    def hm(self, ts: int) -> str:
        return hm(ts, self.tz)

    def new_id(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}_{self.boot}{self.counter:05d}"

    # ------------------------------------------------------------------ outgoing
    def publish(self, msg: dict) -> bool:
        errors = validate(msg)
        if errors:
            self.stats["invalid_outgoing"] += 1
            log.error("refusing to publish invalid %s: %s", msg.get("type"), "; ".join(errors[:3]))
            return False
        try:
            self.publisher(msg)
        except Exception as exc:  # the bus queues QoS 1; a raise here is a bug or a closed bus
            self.stats["publish_errors"] += 1
            log.error("publish failed for %s: %s", msg.get("type"), type(exc).__name__)
            return False
        self.stats["published_" + msg["type"]] += 1
        if msg["type"] == "record":
            self._remember_record(msg)
        return True

    def act(self, agent: str, action: str, *, bed_id: str | None = None, device_id: str | None = None,
            detail: str = "", undo: Callable[[dict, str | None], bool] | None = None,
            undoes: str | None = None, approved_by: str | None = None, result: str = "ok") -> dict | None:
        """The ONLY way an action is taken. Returns the published action, or None if refused."""
        key = "staff" if agent.startswith("staff:") else agent
        if action not in ALLOWED_ACTIONS.get(key, frozenset()):
            self.stats["rejected_actions"] += 1
            self.log.write(event="rejected", ts=self.now(), by=agent, action=action, bed_id=bed_id,
                           reason="not on the allow-list for this agent")
            log.warning("allow-list: %s may not %s (refused, logged)", agent, action)
            return None
        aid = self.new_id("act")
        msg = make_action(action_id=aid, ts=self.now(), by=agent, action=action, bed_id=bed_id,
                          device_id=device_id, detail=clean_text(detail, 480),
                          undo_id=aid if undo else None, undoes=undoes, approved_by=approved_by,
                          result=result)
        if not self.publish(msg):
            self.log.write(event="not_published", ts=self.now(), by=agent, action=action, bed_id=bed_id)
            return None
        self.actions[aid] = msg
        while len(self.actions) > 20000:
            old, _ = self.actions.popitem(last=False)
            self.undo.pop(old, None)
        if undo:
            self.undo[aid] = (agent, undo)
        self.log.write(event="action", **msg)
        self.emit("action", msg)
        return msg

    def publish_alert(self, msg: dict) -> bool:
        ok = self.publish(msg)
        if ok:
            self.log.write(event="alert", **msg)
            self.emit("alert", msg)
        return ok

    def publish_record(self, agent: str, kind: str, record_id: str, data: dict) -> dict | None:
        msg = make_record(kind=kind, record_id=record_id, by=agent, data=data, ts=self.now())
        if not self.publish(msg):
            return None
        self.log.write(event="record", ts=msg["ts"], kind=kind, record_id=record_id, by=agent)
        self.emit("record", msg)
        return msg

    def note(self, **entry: Any) -> None:
        """A visible, non-action log line (e.g. 'telegram off', 'learning, no alert')."""
        self.log.write(event="note", ts=self.now(), **entry)

    def emit(self, name: str, data: dict) -> None:
        for agent in list(self.agents.values()):
            try:
                agent.on_event(name, data)
            except Exception:
                self.stats["agent_errors"] += 1
                log.exception("%s failed on event %s", agent.id, name)

    # ------------------------------------------------------------------ undo
    def refuse(self, request: dict | None, reason: str, **extra: Any) -> None:
        self.stats["refused"] += 1
        self.log.write(event="refused", ts=self.now(), request_id=(request or {}).get("request_id"),
                       action=(request or {}).get("action"), target_id=(request or {}).get("target_id"),
                       by=(request or {}).get("by"), reason=reason, **extra)
        log.info("refused %s: %s", (request or {}).get("action"), reason)

    def undo_request(self, req: dict) -> None:
        target = req["target_id"]
        if target in self.undone:
            return self.refuse(req, "already undone", undone_by=self.undone[target])
        entry = self.undo.get(target)
        if entry is None:
            return self.refuse(req, "unknown or not undoable action")
        owner, fn = entry
        if not fn(self.actions.get(target) or {"action_id": target}, req["by"]):
            self.refuse(req, f"{owner} could not undo now")

    def mark_undone(self, ids, by_action_id: str) -> None:
        for i in ids:
            if i:
                self.undone[i] = by_action_id
                self.undo.pop(i, None)

    # ------------------------------------------------------------------ timers
    def call_at(self, key: str, ts: int, fn: Callable[[], None]) -> None:
        self.timers[key] = (int(ts), fn)

    def cancel(self, key: str) -> None:
        self.timers.pop(key, None)

    def cancel_prefix(self, prefix: str) -> None:
        for key in [k for k in self.timers if k.startswith(prefix)]:
            del self.timers[key]

    def tick(self) -> None:
        with self.lock:
            now = self.now()
            due = sorted((ts, key) for key, (ts, _) in self.timers.items() if ts <= now)
            for ts, key in due:
                entry = self.timers.get(key)
                if entry is None or entry[0] != ts:
                    continue
                del self.timers[key]
                try:
                    entry[1]()
                except Exception:
                    self.stats["timer_errors"] += 1
                    log.exception("timer %s failed", key)

    # ------------------------------------------------------------------ incoming
    def _dedupe(self, key: tuple) -> bool:
        if key in self.seen:
            return True
        self.seen[key] = None
        while len(self.seen) > 5000:
            self.seen.popitem(last=False)
        return False

    def _remember_record(self, msg: dict) -> None:
        self.records[msg["record_id"]] = msg
        self.records.move_to_end(msg["record_id"])
        while len(self.records) > 5000:
            self.records.popitem(last=False)

    def handle(self, msg: dict, topic: str = "") -> None:
        """Bus handler (valid messages only). Never raises."""
        with self.lock:
            try:
                self._handle(msg)
            except Exception:
                self.stats["handler_errors"] += 1
                log.exception("failed to handle %s", msg.get("type"))

    def _handle(self, msg: dict) -> None:
        kind = msg.get("type")
        self.stats["in_" + str(kind)] += 1
        if kind == "verdict":
            self.latest_verdict[msg["bed_id"]] = msg
            self.emit("in_verdict", msg)
            for aid in ("A1", "A2", "A3", "A6", "A7", "A8", "A4", "A5"):
                if aid in self.agents:
                    self.agents[aid].on_verdict(msg)
        elif kind == "bedside_check":
            if self._dedupe(("bedside", msg["bed_id"], msg["ts"], msg["by"], msg["result"])):
                return
            self.emit("in_bedside", msg)
            for agent in list(self.agents.values()):
                agent.on_bedside(msg)
        elif kind == "request":
            if self._dedupe(("request", msg["request_id"])):
                return
            self.emit("in_request", msg)
            self.log.write(event="request", ts=self.now(), request_id=msg["request_id"], action=msg["action"],
                           target_id=clean_text(msg["target_id"], 80), by=msg["by"])
            if msg["action"] == "undo_action":
                return self.undo_request(msg)
            route = REQUEST_ROUTES.get(msg["action"])
            agent = self.agents.get(route[0]) if route else None
            if agent is None:
                return self.refuse(msg, "no agent handles this request")
            getattr(agent, route[1])(msg)
        elif kind == "demo_control":
            if self._dedupe(("demo", msg["cmd"], msg["run_id"], msg["ts"])):
                return
            self.reset(msg)
            if msg["cmd"] == "run":
                self.run_info = {"run_id": msg["run_id"], "start_at_s": msg["start_at_s"], "ts": msg["ts"],
                                 "speed": msg.get("speed") if isinstance(msg.get("speed"), (int, float)) and msg.get("speed") > 0 else 1}
                for agent in list(self.agents.values()):
                    agent.on_run(msg)
        elif kind == "record":
            if msg["by"] in self.agents and msg["record_id"] in self.records:
                return  # our own record coming back
            self._remember_record(msg)
        elif kind == "score":
            self.emit("in_score", msg)

    # ------------------------------------------------------------------ reset
    def reset(self, msg: dict | None = None) -> None:
        with self.lock:
            keep = {k: v for k, v in self.undo.items() if v[0] == "A2"}
            for agent in list(self.agents.values()):
                try:
                    agent.reset()
                except Exception:
                    self.stats["agent_errors"] += 1
                    log.exception("%s reset failed", agent.id)
            self.timers.clear()
            self.latest_verdict.clear()
            a2 = self.agents.get("A2")
            live = a2.undoable_ids() if a2 is not None and hasattr(a2, "undoable_ids") else set()
            self.undo = {k: v for k, v in keep.items() if k in live}
            if self.telegram is not None:
                self.telegram.reset()
            self.run_info = None
            self.stats["resets"] += 1
            self.log.write(event="reset", ts=self.now(), cmd=(msg or {}).get("cmd", "reset"),
                           run_id=(msg or {}).get("run_id"))
            for agent in list(self.agents.values()):
                if hasattr(agent, "after_reset"):
                    agent.after_reset()

    def snapshot(self) -> dict:
        with self.lock:
            snap = {"ts": self.now(), "stats": dict(self.stats), "timers": sorted(self.timers),
                    "agents": {aid: a.snapshot() for aid, a in self.agents.items()}}
            if self.telegram is not None and hasattr(self.telegram, "stats"):
                snap["telegram"] = self.telegram.stats()
            return snap
