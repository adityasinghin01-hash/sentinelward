"""Acceptance checks 1, 2, 3, 5, 7 and 8 on one full 20-minute fake-clock run."""

from __future__ import annotations

import json

import numpy as np
import pytest
import sw_common

from conftest import ALARMS, B01_CUFF, B01_NAN_ECG, B02_HR_NAN_S, B02_HR_ZERO_S, B08_CUFF, FS


def t_of(msg: dict, origin_ms: int) -> int:
    assert (msg["ts"] - origin_ms) % 1000 == 0
    return (msg["ts"] - origin_ms) // 1000


# ---------------------------------------------------------------- check 1: message counts

def test_message_counts_per_bed(full_run):
    result, bus, _, _ = full_run
    counts = {bed: len(msgs) for bed, msgs in bus.by_bed().items()}
    for bed in ("B01", "B02", "B05", "B06", "B08", "B09", "B10", "B11", "B12"):
        assert counts[bed] == 1200, bed
    assert counts["B03"] == 330            # T+00:00 .. T+05:29
    assert counts["B04"] == 330            # T+01:30 .. T+06:59
    assert counts["B07"] == 330            # T+09:00 .. T+14:29
    assert result.status == "complete"
    assert result.sent == sum(counts.values())
    assert result.invalid == 0 and result.publish_errors == 0


def test_send_windows(full_run):
    result, bus, _, _ = full_run
    by_bed = bus.by_bed()
    windows = {bed: (t_of(m[0], result.origin_ms), t_of(m[-1], result.origin_ms)) for bed, m in by_bed.items()}
    assert windows["B03"] == (0, 329)
    assert windows["B04"] == (90, 419)
    assert windows["B07"] == (540, 869)
    assert windows["B12"] == (0, 1199)    # a pack longer than the run is cut at T+20:00, not looped


# ---------------------------------------------------------------- check 2: monitor alarms

@pytest.mark.parametrize("bed, t_s", [("B03", 300), ("B04", 390), ("B07", 840)])
def test_alarm_in_exactly_one_message(full_run, bed, t_s):
    result, bus, _, _ = full_run
    with_alarm = [m for m in bus.by_bed()[bed] if m["monitor_alarm"] is not None]
    assert len(with_alarm) == 1
    assert t_of(with_alarm[0], result.origin_ms) == t_s
    assert with_alarm[0]["monitor_alarm"] == {"code": ALARMS[bed]["code"], "priority": "high"}


def test_no_alarms_on_other_beds(full_run):
    _, bus, _, _ = full_run
    for bed, msgs in bus.by_bed().items():
        if bed not in ALARMS:
            assert all(m["monitor_alarm"] is None for m in msgs), bed


# ---------------------------------------------------------------- check 3: nibp

def test_nibp_only_on_new_cuff_readings(full_run):
    result, bus, _, _ = full_run
    for bed, cuff in (("B01", B01_CUFF), ("B08", B08_CUFF)):
        with_nibp = [m for m in bus.by_bed()[bed] if m["nibp"] is not None]
        assert [t_of(m, result.origin_ms) for m in with_nibp] == [int(c[0]) for c in cuff]
        for m, (t, s, d, mp) in zip(with_nibp, cuff):
            assert m["nibp"] == {"sys": int(s), "dia": int(d), "map": int(mp), "ts": result.origin_ms + round(t * 1000)}
    for bed, msgs in bus.by_bed().items():
        if bed not in ("B01", "B08"):
            assert all(m["nibp"] is None for m in msgs), bed


# ---------------------------------------------------------------- check 5: seq

def test_seq_contiguous_per_device(full_run):
    _, bus, _, _ = full_run
    for bed, msgs in bus.by_bed().items():
        assert [m["seq"] for m in msgs] == list(range(1, len(msgs) + 1)), bed
        assert len({m["device_id"] for m in msgs}) == 1


# ---------------------------------------------------------------- check 7: validity, NaN, zero

def test_every_message_valid(full_run):
    _, bus, _, _ = full_run
    assert bus.validation_errors == []


def test_shape_and_rounding(full_run, packs):
    result, bus, _, _ = full_run
    for m in bus.messages[:200]:
        assert m["type"] == "vitals" and m["v"] == 1 and m["fs"] == FS
        for ch, decimals in (("ecg", 3), ("ppg", 2), ("abp", 1)):
            if m[ch] is None:
                continue
            assert len(m[ch]) == FS
            for x in m[ch]:
                if x is not None:
                    assert isinstance(x, float) and round(x, decimals) == x
        assert len(sw_common.encode(m)) < 4096
    # B04's pack has no arterial line -> abp is null in every message
    assert all(m["abp"] is None for m in bus.by_bed()["B04"])
    # samples are the pack's own values
    b09 = bus.by_bed()["B09"][123]
    raw = packs["B09"].wave("ecg", 123)
    assert b09["ecg"] == (np.round(raw, 3) + 0.0).tolist()


def test_nan_sample_sent_as_null(full_run):
    _, bus, _, _ = full_run
    sec, smp = B01_NAN_ECG
    msg = bus.by_bed()["B01"][sec]
    assert msg["seq"] == sec + 1               # the second with a NaN sample is sent, not skipped
    assert msg["ecg"][smp] is None
    decoded = json.loads(sw_common.encode(msg))
    assert decoded["ecg"][smp] is None
    assert decoded["ecg"][smp + 1] is not None


def test_hr_zero_stays_zero_and_nan_is_null(full_run):
    _, bus, _, _ = full_run
    b02 = bus.by_bed()["B02"]
    assert b02[B02_HR_ZERO_S]["hr"] == 0
    assert json.loads(sw_common.encode(b02[B02_HR_ZERO_S]))["hr"] == 0
    assert b02[B02_HR_NAN_S]["hr"] is None
    assert isinstance(b02[B02_HR_NAN_S + 1]["hr"], int)


# ---------------------------------------------------------------- check 8: event log

def test_event_log(full_run):
    result, _, events, _ = full_run
    assert all(e["run_id"] == "run_test" for e in events)
    assert all(set(e) == {"run_id", "t_s", "ts", "bed_id", "event", "detail"} for e in events)
    assert all(e["ts"] == result.origin_ms + int(e["t_s"] * 1000) for e in events)

    def find(event: str, bed: str | None = None) -> list[dict]:
        return [e for e in events if e["event"] == event and (bed is None or e["bed_id"] == bed)]

    assert events[0]["event"] == "run_start" and events[0]["t_s"] == 0
    assert events[-1]["event"] == "run_end" and events[-1]["t_s"] == 1200
    assert events[-1]["detail"]["reason"] == "complete"
    assert [e["t_s"] for e in find("bed_join", "B04")] == [90]
    assert [e["t_s"] for e in find("bed_join", "B07")] == [540]
    assert len(find("bed_join")) == 12
    alarms = {e["bed_id"]: e for e in find("monitor_alarm")}
    assert {b: e["t_s"] for b, e in alarms.items()} == {"B03": 300, "B04": 390, "B07": 840}
    assert {b: e["detail"]["code"] for b, e in alarms.items()} == {"B03": "VTACH", "B04": "ASYSTOLE", "B07": "VFIB"}
    assert {b: e["detail"]["true_alarm"] for b, e in alarms.items()} == {"B03": True, "B04": False, "B07": True}
    assert [(e["event"], e["t_s"], e["bed_id"]) for e in events if e["event"].startswith("drift_")] == [
        ("drift_start", 300, "B08"), ("drift_full", 720, "B08"), ("drift_end", 900, "B08")]
    assert {e["bed_id"]: e["t_s"] for e in find("source_end")} == {"B03": 330, "B04": 420, "B07": 870}
    assert [e["t_s"] for e in events] == sorted(e["t_s"] for e in events)


def test_sent_csv(full_run):
    result, _, _, _ = full_run
    lines = (result.run_dir / "sent.csv").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "t_s,sent,max_lag_ms"
    rows = [line.split(",") for line in lines[1:]]
    assert len(rows) == 1200
    assert [int(r[0]) for r in rows] == list(range(1200))
    sent = {int(r[0]): int(r[1]) for r in rows}
    assert sent[0] == 10          # 9 full beds + B03
    assert sent[90] == 11         # B04 joins
    assert sent[330] == 10        # B03 gone
    assert sent[540] == 10        # B04 gone, B07 joins
    assert sent[1199] == 9
    assert sum(sent.values()) == result.sent
