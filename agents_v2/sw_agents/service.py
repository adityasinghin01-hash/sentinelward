"""The one agents process: Bus <-> Engine, timer tick, background worker, Telegram threads.

Run: python -m sw_agents   (or the sw-agents2 script). Settings: deploy/agents2.env.example.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import signal
import threading
import time
from pathlib import Path
from typing import Callable

from sw_common import BEDSIDE_SUB, DEMO_CONTROL_TOPIC, RECORD_TOPIC, REQUEST_TOPIC, VERDICT_SUB

from .agents.a1_alerts import A1Alerts
from .agents.a2_contain import A2Contain
from .agents.a3_evidence import A3Evidence
from .agents.a4_fleet import A4Fleet
from .agents.a5_report import A5Report
from .agents.a6_tickets import A6Tickets
from .agents.a7_workload import A7Workload
from .agents.a8_briefing import A8Briefing
from .config import Settings
from .engine import Engine
from .telegram import Telegram

log = logging.getLogger("sw_agents")


def subscriptions(settings: Settings) -> list[str]:
    return [VERDICT_SUB, BEDSIDE_SUB, REQUEST_TOPIC, DEMO_CONTROL_TOPIC, RECORD_TOPIC, *settings.extra_subscriptions]


class RedactFilter(logging.Filter):
    """Belt and braces: no configured secret ever reaches a log line."""

    def __init__(self, secrets: tuple[str, ...]) -> None:
        super().__init__()
        self.secrets = [s for s in secrets if len(s) >= 4]

    def filter(self, record: logging.LogRecord) -> bool:
        if self.secrets:
            text = record.getMessage()
            if any(s in text for s in self.secrets):
                for s in self.secrets:
                    text = text.replace(s, "[redacted]")
                record.msg, record.args = text, ()
        return True


class Worker:
    """One background thread for slow work (hub control, Granite) so handlers never block."""

    def __init__(self, name: str = "sw-agents-worker") -> None:
        self.q: queue.Queue[Callable[[], None] | None] = queue.Queue(maxsize=1000)
        self.thread = threading.Thread(target=self._run, name=name, daemon=True)
        self.thread.start()

    def __call__(self, fn: Callable[[], None]) -> None:
        try:
            self.q.put_nowait(fn)
        except queue.Full:
            log.error("background queue full; work dropped")

    def _run(self) -> None:
        while True:
            fn = self.q.get()
            if fn is None:
                return
            try:
                fn()
            except Exception:
                log.exception("background work failed")

    def stop(self) -> None:
        self.q.put(None)


def build(settings: Settings, publisher, clock=None, background=None, *, broker=None, writer=None,
          telegram_http=None, granite_background=None) -> Engine:
    """Wire the engine and A1-A8. Used by the service and by the tests.

    granite_background: A8's own thread, so a slow Granite call never delays a hub cut-off.
    """
    engine = Engine(settings, publisher, clock, background)
    engine.telegram = Telegram(settings.telegram_token, engine.clock, min_interval_s=settings.telegram_min_interval_s,
                               http=telegram_http)
    engine.register(A1Alerts(engine))
    engine.register(A2Contain(engine, broker))
    engine.register(A3Evidence(engine))
    engine.register(A4Fleet(engine))
    engine.register(A5Report(engine))
    engine.register(A6Tickets(engine))
    engine.register(A7Workload(engine))
    engine.register(A8Briefing(engine, writer, granite_background))
    for agent in engine.agents.values():
        if hasattr(agent, "after_reset"):
            agent.after_reset()
    return engine


def main() -> int:
    logging.basicConfig(level=os.environ.get("SW_LOG_LEVEL", "INFO").upper(),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()
    redact = RedactFilter(settings.secrets())
    for handler in logging.getLogger().handlers:
        handler.addFilter(redact)

    from sw_common import Bus
    bus = Bus(settings.mqtt_host, settings.mqtt_port, settings.client_id, username=settings.mqtt_username,
              password=settings.mqtt_password, tls_ca_file=settings.mqtt_ca_file)
    worker = Worker()
    granite_worker = Worker("sw-agents-granite")
    engine = build(settings, bus.publish, background=worker, granite_background=granite_worker)
    log.info("agents_v2 starting: hub %s:%s as %s; A2 %s; telegram %s; granite %s; state %s",
             settings.mqtt_host, settings.mqtt_port, settings.client_id,
             "DRY RUN" if settings.a2_dry_run else "hub control", "on" if settings.telegram_token else "off",
             "set" if settings.granite_url else "not set (template)", settings.state_dir)
    bus.subscribe(subscriptions(settings), engine.handle)
    if not bus.connect(wait_s=5):
        log.warning("hub not reachable yet; retrying in the background")

    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())

    def ticker() -> None:
        last_status = 0.0
        while not stop.is_set():
            engine.tick()
            if time.monotonic() - last_status > 10:
                last_status = time.monotonic()
                _write_status(Path(settings.state_dir) / "status.json", engine, bus)
            stop.wait(0.2)

    def poller() -> None:
        while not stop.is_set():
            try:
                presses = engine.telegram.poll(timeout_s=20)
            except Exception as exc:
                log.warning("telegram poll failed: %s", type(exc).__name__)
                presses = []
                stop.wait(5)
            for press in presses:
                with engine.lock:
                    try:
                        engine.agents["A1"].on_telegram(press)
                    except Exception:
                        log.exception("telegram press failed")

    def sender() -> None:
        while not stop.is_set():
            if not engine.telegram.pump():
                stop.wait(0.1)

    threads = [threading.Thread(target=ticker, name="sw-agents-tick", daemon=True)]
    if engine.telegram.enabled:
        threads.append(threading.Thread(target=poller, name="sw-agents-telegram", daemon=True))
        threads.append(threading.Thread(target=sender, name="sw-agents-telegram-send", daemon=True))
    for t in threads:
        t.start()
    stop.wait()
    log.info("agents_v2 stopping")
    worker.stop()
    granite_worker.stop()
    bus.close()
    engine.telegram.close()
    return 0


def _write_status(path: Path, engine: Engine, bus) -> None:
    try:
        snap = engine.snapshot()
        snap["bus"] = bus.stats()
        snap["connected"] = bus.is_connected
        tmp = path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(snap, fh, default=str)
        os.replace(tmp, path)
    except Exception as exc:
        log.warning("status write failed: %s", type(exc).__name__)


if __name__ == "__main__":
    raise SystemExit(main())
