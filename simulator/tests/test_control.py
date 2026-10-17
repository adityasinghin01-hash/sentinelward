"""Acceptance check 10 (reset on the control topic) and seq restart after reset (check 5)."""

from __future__ import annotations

import threading
import time

import pytest
import sw_common

from conftest import FakeBus, read_events
from sw_sim.clock import RealClock
from sw_sim.engine import STOP_SIGNAL, WardRun
from sw_sim.listen import ControlError, Controller, parse_control


def control(cmd: str, run_id: str = "run_20261017_160000", start_at_s: float = 0) -> dict:
    return {"v": 1, "type": "demo_control", "ts": int(time.time() * 1000), "cmd": cmd, "run_id": run_id,
            "start_at_s": start_at_s}


def wait_for(predicate, timeout: float = 5.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


@pytest.fixture
def controller_setup(script, packs, tmp_path):
    bus = FakeBus()
    small = script.select(["B01", "B03"])

    def factory(run_id: str, start_at_s: int) -> WardRun:
        return WardRun(small, packs, run_id=run_id, runs_dir=tmp_path / "runs", clock=RealClock(), bus=bus,
                       start_at_s=start_at_s)

    controller = Controller(factory, small.run_length_s)
    bus.subscribe(sw_common.DEMO_CONTROL_TOPIC, controller.on_message)
    shutdown = threading.Event()
    server = threading.Thread(target=controller.serve, args=(shutdown,), daemon=True)
    server.start()
    yield controller, bus, shutdown, tmp_path / "runs"
    shutdown.set()
    server.join(5)


def test_reset_stops_within_one_second(controller_setup):
    controller, bus, _, runs = controller_setup
    bus.inject(sw_common.DEMO_CONTROL_TOPIC, control("run", "run_a", start_at_s=295))
    assert wait_for(lambda: len(bus.messages) >= 4, timeout=8)
    t0 = time.monotonic()
    bus.inject(sw_common.DEMO_CONTROL_TOPIC, control("reset", "run_a"))
    assert wait_for(lambda: len(controller.results) == 1, timeout=2)
    assert time.monotonic() - t0 < 1.0
    sent_before = len(bus.messages)
    time.sleep(1.2)
    assert len(bus.messages) == sent_before       # nothing after the reset
    result = controller.results[0]
    assert result.status == "reset"
    events = read_events(result.run_dir)
    assert events[0]["event"] == "run_start" and events[0]["t_s"] == 295
    assert events[-1]["event"] == "run_reset" and events[-1]["run_id"] == "run_a"
    assert 295 < events[-1]["t_s"] < 305
    # the alarm at T+05:00 (pack second 300) arrived in this run
    assert any(m["monitor_alarm"] for m in bus.messages if m["bed_id"] == "B03") == (result.next_t_s > 300)
    # files are complete: every line parses, sent.csv rows end with a newline
    assert (result.run_dir / "sent.csv").read_text().endswith("\n")


def test_seq_restarts_after_reset(controller_setup):
    controller, bus, _, _ = controller_setup
    bus.inject(sw_common.DEMO_CONTROL_TOPIC, control("run", "run_one"))
    assert wait_for(lambda: len(bus.messages) >= 6, timeout=8)
    bus.inject(sw_common.DEMO_CONTROL_TOPIC, control("reset", "run_one"))
    assert wait_for(lambda: len(controller.results) == 1, timeout=2)
    first = list(bus.messages)
    bus.inject(sw_common.DEMO_CONTROL_TOPIC, control("run", "run_two"))
    assert wait_for(lambda: len(bus.messages) >= len(first) + 4, timeout=8)
    bus.inject(sw_common.DEMO_CONTROL_TOPIC, control("reset", "run_two"))
    assert wait_for(lambda: len(controller.results) == 2, timeout=2)
    second = bus.messages[len(first):]
    for msgs in (first, second):
        for bed in ("B01", "B03"):
            seqs = [m["seq"] for m in msgs if m["bed_id"] == bed]
            assert seqs == list(range(1, len(seqs) + 1)), (bed, seqs)
    assert [r.status for r in controller.results] == ["reset", "reset"]


def test_new_run_replaces_current(controller_setup):
    controller, bus, _, _ = controller_setup
    bus.inject(sw_common.DEMO_CONTROL_TOPIC, control("run", "run_x"))
    assert wait_for(lambda: len(bus.messages) >= 2, timeout=8)
    bus.inject(sw_common.DEMO_CONTROL_TOPIC, control("run", "run_y", start_at_s=600))
    assert wait_for(lambda: len(controller.results) == 1, timeout=3)
    assert controller.results[0].status == "reset"
    assert wait_for(lambda: controller.current is not None and controller.current.run_id == "run_y", timeout=3)


def test_shutdown_writes_run_end(controller_setup):
    controller, bus, shutdown, _ = controller_setup
    bus.inject(sw_common.DEMO_CONTROL_TOPIC, control("run", "run_s"))
    assert wait_for(lambda: len(bus.messages) >= 2, timeout=8)
    shutdown.set()
    assert wait_for(lambda: len(controller.results) == 1, timeout=3)
    events = read_events(controller.results[0].run_dir)
    assert events[-1]["event"] == "run_end" and events[-1]["detail"]["reason"] == "shutdown"


def test_signal_stop_finishes_the_second(script, packs, tmp_path):
    bus = FakeBus()
    run = WardRun(script.select(["B01", "B02"]), packs, run_id="run_sig", runs_dir=tmp_path, clock=RealClock(), bus=bus)
    threading.Timer(2.5, run.request_stop, args=(STOP_SIGNAL,)).start()
    result = run.run()
    assert result.status == "signal"
    by_bed = bus.by_bed()
    assert len(by_bed["B01"]) == len(by_bed["B02"])   # never half a second
    events = read_events(result.run_dir)
    assert events[-1]["event"] == "run_end" and events[-1]["detail"]["reason"] == "signal"


def test_reset_before_first_second(script, packs, tmp_path):
    bus = FakeBus()
    run = WardRun(script.select(["B01"]), packs, run_id="run_early", runs_dir=tmp_path, clock=RealClock(), bus=bus)
    run.request_stop("reset")
    result = run.run()
    assert bus.messages == []
    assert [e["event"] for e in read_events(result.run_dir)] == ["run_start", "run_reset"]


@pytest.mark.parametrize("message", [
    {"v": 1, "type": "vitals", "cmd": "run", "run_id": "run_a"},
    {"v": 2, "type": "demo_control", "cmd": "run", "run_id": "run_a"},
    {"v": 1, "type": "demo_control", "cmd": "stop", "run_id": "run_a"},
    {"v": 1, "type": "demo_control", "cmd": "run", "run_id": "../etc"},
    {"v": 1, "type": "demo_control", "cmd": "run", "run_id": "run_a", "start_at_s": 1200},
    {"v": 1, "type": "demo_control", "cmd": "run", "run_id": "run_a", "start_at_s": "10"},
    "not a dict",
])
def test_bad_control_messages_rejected(message):
    with pytest.raises(ControlError):
        parse_control(message, 1200)


def test_control_parsing():
    assert parse_control(control("run", "run_b", 270.9), 1200).start_at_s == 270
    assert parse_control({"v": 1, "type": "demo_control", "cmd": "reset"}, 1200).cmd == "reset"
