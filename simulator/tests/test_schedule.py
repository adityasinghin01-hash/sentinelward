"""Acceptance checks 6 (--start-at) and 9 (no schedule drift), plus clock behaviour."""

from __future__ import annotations

import threading
import time

import pytest

from conftest import FakeClock, play
from sw_sim.clock import InstantClock, RealClock, VirtualClock, make_clock
from sw_sim.config import format_t, parse_start_at
from sw_sim.engine import round_samples


# ---------------------------------------------------------------- check 6: --start-at

def test_start_at_positions(script, packs, tmp_path):
    result, bus, events, _ = play(script, packs, tmp_path, start_at_s=parse_start_at("T+04:30"))
    by_bed = bus.by_bed()
    origin = result.origin_ms
    first_b03, first_b04 = by_bed["B03"][0], by_bed["B04"][0]
    assert (first_b03["ts"] - origin) // 1000 == 270
    assert first_b03["ecg"] == round_samples(packs["B03"].wave("ecg", 270), 3)   # pack second 270
    assert first_b04["ecg"] == round_samples(packs["B04"].wave("ecg", 180), 3)   # pack second 180
    joins = {e["bed_id"]: e["detail"]["pack_second"] for e in events if e["event"] == "bed_join"}
    assert joins["B03"] == 270 and joins["B04"] == 180
    assert (by_bed["B07"][0]["ts"] - origin) // 1000 == 540                    # still joins at T+09:00
    # the first B03 alarm comes 30 s later (T+05:00)
    alarm_msgs = [m for m in by_bed["B03"] if m["monitor_alarm"]]
    assert [(m["ts"] - origin) // 1000 for m in alarm_msgs] == [300]
    assert alarm_msgs[0]["ts"] - first_b03["ts"] == 30_000
    # seq restarts at 1 for this run; message counts follow the remaining script
    assert first_b03["seq"] == 1 and len(by_bed["B03"]) == 60 and len(by_bed["B01"]) == 930
    start = events[0]
    assert start["event"] == "run_start" and start["t_s"] == 270
    assert start["detail"]["beds"]["B07"]["state_at_start"] == "waiting"
    assert start["detail"]["drift"]["offset_mmHg_at_start"] == 0.0
    # events before the start point did not happen in this run
    assert not [e for e in events if e["t_s"] < 270]


def test_start_at_inside_drift(script, packs, tmp_path):
    result, bus, events, _ = play(script, packs, tmp_path, start_at_s=534)
    assert events[0]["detail"]["drift"]["offset_mmHg_at_start"] == pytest.approx(8.357, abs=0.001)
    assert "drift_start" not in {e["event"] for e in events}
    assert {e["event"] for e in events} >= {"drift_full", "drift_end"}
    b03 = events[0]["detail"]["beds"]["B03"]
    assert b03["state_at_start"] == "ended"
    assert "B03" not in bus.by_bed()
    assert not [e for e in events if e["event"] == "source_end" and e["bed_id"] == "B03"]


@pytest.mark.parametrize("text, seconds", [("T+04:30", 270), ("04:30", 270), ("T+00:00", 0), ("T+19:59", 1199),
                                           ("270", 270), ("T+90", 90)])
def test_parse_start_at(text, seconds):
    assert parse_start_at(text) == seconds


@pytest.mark.parametrize("bad", ["T-04:30", "4m30", "T+04:60", ""])
def test_parse_start_at_rejects(bad):
    with pytest.raises(ValueError):
        parse_start_at(bad)


def test_format_t():
    assert format_t(534) == "T+08:54"


# ---------------------------------------------------------------- check 9: no drift in the schedule

def test_schedule_is_absolute_under_jitter(script, packs, tmp_path):
    clock = FakeClock(jitter_ms=20.0, seed=7)
    result, bus, _, _ = play(script.select(["B01", "B03"]), packs, tmp_path, clock=clock)
    origin = result.origin_ms
    assert result.schedule == [origin + k * 1000 for k in range(1200)]
    assert clock.targets[:1200] == [origin + k * 1000 for k in range(1200)]
    for bed, msgs in bus.by_bed().items():
        assert [m["ts"] for m in msgs] == [origin + k * 1000 for k in range(len(msgs))], bed
    assert result.lag_max_ms <= 20.0
    assert origin % 1000 == 0


def test_origin_is_a_whole_second_with_lead(script, packs, tmp_path):
    clock = FakeClock(start_ms=1_792_252_800_437.0)
    result, _, _, _ = play(script.select(["B01"]), packs, tmp_path, clock=clock)
    assert result.origin_ms == 1_792_252_802_000   # next whole second + lead_ms 1000


# ---------------------------------------------------------------- clocks

def test_real_clock_waits_to_target_and_stops_early():
    clock = RealClock()
    stop = threading.Event()
    target = clock.now_ms() + 120
    assert clock.wait_until(target, stop) is False
    assert clock.now_ms() >= target
    assert abs(clock.now_ms() - time.time() * 1000) < 50
    threading.Timer(0.1, stop.set).start()
    t0 = time.monotonic()
    assert clock.wait_until(clock.now_ms() + 10_000, stop) is True
    assert time.monotonic() - t0 < 0.5


def test_virtual_and_instant_clocks():
    stop = threading.Event()
    v = VirtualClock(50)
    t0 = time.monotonic()
    target = v.now_ms() + 5000           # 5 virtual seconds = 0.1 real s
    assert v.wait_until(target, stop) is False
    assert time.monotonic() - t0 < 1.0 and v.now_ms() >= target and v.fast
    i = InstantClock(start_ms=1000.0)
    assert i.wait_until(5000.0, stop) is False and i.now_ms() == 5000.0
    with pytest.raises(ValueError):
        make_clock(0.5, False)
    assert isinstance(make_clock(1, False), RealClock)
    assert isinstance(make_clock(1, True), InstantClock)
    assert isinstance(make_clock(10, False), VirtualClock)


def test_fast_run_is_marked(script, packs, tmp_path):
    from sw_sim.engine import WardRun
    from conftest import FakeBus, read_events
    run = WardRun(script.select(["B01"]), packs, run_id="run_fast", runs_dir=tmp_path, clock=InstantClock(),
                  bus=FakeBus())
    result = run.run()
    events = read_events(result.run_dir)
    assert events[0]["detail"]["fast"] is True and events[-1]["detail"]["fast"] is True
    assert result.sent == 1200
