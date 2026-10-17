"""Fake bus, fake clock, fake hub broker and fake HTTP: no broker, no network in unit tests."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from sw_common import (encode, make_bedside_check, make_demo_control, make_record, make_request, make_verdict,
                       validate, window_start_for)
from sw_agents.clock import FakeClock
from sw_agents.config import Settings
from sw_agents.granite import GraniteWriter
from sw_agents.service import build


class FakeBus:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    def publish(self, msg: dict) -> bool:
        encode(msg)  # raises MessageError if invalid, exactly like sw_common.Bus.publish
        self.sent.append(copy.deepcopy(msg))
        return True

    def of(self, mtype: str) -> list[dict]:
        return [m for m in self.sent if m["type"] == mtype]

    def actions(self, action: str | None = None, by: str | None = None) -> list[dict]:
        return [m for m in self.of("action") if (action is None or m["action"] == action) and (by is None or m["by"] == by)]

    def alerts(self, alert_id: str | None = None) -> list[dict]:
        return [m for m in self.of("alert") if alert_id is None or m["alert_id"] == alert_id]

    def records(self, kind: str | None = None) -> list[dict]:
        return [m for m in self.of("record") if kind is None or m["kind"] == kind]

    def latest_record(self, record_id: str) -> dict:
        return [m for m in self.of("record") if m["record_id"] == record_id][-1]


class FakeBroker:
    mode = "hub"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail_disable = False
        self.fail_enable = False

    def disable(self, device: str) -> None:
        self.calls.append(("disable", device))
        if self.fail_disable:
            raise RuntimeError("Broker rejected control command; diagnostics withheld")

    def enable(self, device: str) -> None:
        self.calls.append(("enable", device))
        if self.fail_enable:
            raise RuntimeError("Broker control unavailable or timed out")


class FakeResponse:
    def __init__(self, data, status: int = 200) -> None:
        self._data, self.status_code = data, status

    def json(self):
        return self._data


class FakeTelegramHTTP:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.next_id = 100
        self.updates: list[dict] = []
        self.raise_exc: Exception | None = None

    def post(self, method: str, json: dict):
        if self.raise_exc:
            raise self.raise_exc
        self.calls.append((method, copy.deepcopy(json)))
        if method == "sendMessage":
            self.next_id += 1
            return FakeResponse({"ok": True, "result": {"message_id": self.next_id}})
        if method == "getUpdates":
            ups, self.updates = self.updates, []
            return FakeResponse({"ok": True, "result": ups})
        return FakeResponse({"ok": True, "result": True})

    def sends(self, method: str | None = None) -> list[tuple[str, dict]]:
        return [c for c in self.calls if c[0] in ((method,) if method else ("sendMessage", "editMessageText"))]


class FakeGraniteHTTP:
    def __init__(self, text: str | None = None, exc: Exception | None = None) -> None:
        self.text, self.exc, self.prompts = text, exc, []

    def post(self, url: str, json: dict):
        self.prompts.append((url, json))
        if self.exc:
            raise self.exc
        return FakeResponse({"choices": [{"text": self.text}]})


class World:
    def __init__(self, engine, bus: FakeBus, clock: FakeClock, broker: FakeBroker, tg_http, state_dir: Path) -> None:
        self.e, self.bus, self.clock, self.broker, self.tg_http, self.state_dir = engine, bus, clock, broker, tg_http, state_dir
        self.n = 0

    @property
    def a(self):
        return self.e.agents

    def advance(self, seconds: float, step: float = 0.5) -> None:
        """Move the fake clock forward in small steps, firing due timers like the 0.2 s ticker."""
        end = self.clock.t + int(seconds * 1000)
        while self.clock.t < end:
            self.clock.t = min(end, self.clock.t + int(step * 1000))
            self.e.tick()

    def verdict(self, bed: str, verdict: str, conf: float = 0.9, *, reasons=None, scores=None, trust=None,
                last_trusted_ts=None, n: int = 1, every_s: float = 5.0) -> dict:
        msg = None
        for i in range(n):
            if i:
                self.advance(every_s)
            now = self.clock.now_ms()
            sc = scores if scores is not None else {"M1": 0.1, "M2": 0.1, "M3": 0.1, "M4": 0.1, "M5": 0.1, "M6": 0.1}
            tr = trust if trust is not None else (0.95 if verdict in ("NORMAL", "EMERGENCY", "LOOSE_SENSOR", "DRIFTING") else 0.1)
            lt = last_trusted_ts if last_trusted_ts is not None else (None if verdict == "NORMAL" else now - 20_000)
            msg = make_verdict(bed_id=bed, ts=now, window_start=window_start_for(now), verdict=verdict, confidence=conf,
                               trust=tr, last_trusted_ts=lt, reasons=list(reasons or [f"{verdict} reason"]), scores=sc)
            assert validate(msg) == []
            self.e.handle(msg, f"ward/bed/{bed}/verdict")
        return msg

    def request(self, action: str, target: str, by: str = "staff:sam", bed: str | None = None, note: str = "") -> dict:
        self.n += 1
        msg = make_request(request_id=f"req_{self.n:04d}", ts=self.clock.now_ms(), by=by, action=action,
                           target_id=target, bed_id=bed, note=note)
        assert validate(msg) == []
        self.e.handle(msg, "ward/request")
        return msg

    def bedside(self, bed: str, result: str, by: str = "staff:priya") -> dict:
        msg = make_bedside_check(bed_id=bed, result=result, by=by, ts=self.clock.now_ms())
        self.e.handle(msg, f"ward/bed/{bed}/bedside")
        return msg

    def demo(self, cmd: str, run_id: str = "run_test", start_at_s: int = 0, **extra) -> dict:
        msg = make_demo_control(cmd=cmd, run_id=run_id, start_at_s=start_at_s, ts=self.clock.now_ms(), **extra)
        self.e.handle(msg, "ward/demo/control")
        return msg

    def record(self, kind: str, record_id: str, by: str, data: dict) -> dict:
        msg = make_record(kind=kind, record_id=record_id, by=by, data=data, ts=self.clock.now_ms())
        self.e.handle(msg, "ward/record")
        return msg

    def log_lines(self) -> list[dict]:
        path = self.state_dir / "actions.jsonl"
        return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


@pytest.fixture
def make_world(tmp_path):
    worlds: list[World] = []

    def _make(*, broker=None, granite_http=None, granite_url=None, telegram=False, state_dir=None, **overrides):
        state = state_dir or (tmp_path / "state")
        if telegram:
            overrides.setdefault("telegram_token", "123456:SECRET-TOKEN-abcdef")
            overrides.setdefault("telegram_chats", {"staff:priya": 1001, "staff:tom": 1002, "staff:dr_mehta": 1003})
            overrides.setdefault("telegram_it_chat", 2001)
        overrides.setdefault("dynsec_options", "/nonexistent/admin.conf")  # A2 'hub' mode with the fake broker
        settings = Settings(state_dir=state, granite_url=granite_url, **overrides)
        clock = FakeClock()
        bus = FakeBus()
        broker = None if broker == "auto" else (broker if broker is not None else FakeBroker())
        tg_http = FakeTelegramHTTP() if telegram else None
        writer = GraniteWriter(granite_url, http=granite_http) if granite_http is not None else GraniteWriter(granite_url)
        engine = build(settings, bus.publish, clock, broker=broker, writer=writer, telegram_http=tg_http)
        w = World(engine, bus, clock, broker, tg_http, Path(state))
        worlds.append(w)
        return w

    yield _make
    for w in worlds:  # every outgoing message passed sw_common.validate
        assert all(validate(m) == [] for m in w.bus.sent)
        assert w.e.stats["invalid_outgoing"] == 0
        assert w.e.stats["handler_errors"] == 0, "a handler raised"
        assert w.e.stats["agent_errors"] == 0
        assert w.e.stats["timer_errors"] == 0


@pytest.fixture
def world(make_world):
    return make_world()
