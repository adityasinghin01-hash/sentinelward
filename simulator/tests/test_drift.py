"""Acceptance check 4: the B08 arterial-line drift."""

from __future__ import annotations

import numpy as np
import pytest

from sw_sim.drift import DriftSpec, offset_at, offsets_for_second
from sw_sim.engine import round_samples


@pytest.mark.parametrize("t_s, expected, tol", [
    (299, 0.0, 0.0),           # T+04:59
    (300, 0.0, 0.0),           # T+05:00, ramp begins at 0
    (534, 8.36, 0.05),         # T+08:54
    (666, 13.07, 0.05),        # T+11:06
    (720, 15.0, 0.0),          # T+12:00
    (899, 15.0, 0.0),          # T+14:59
    (900, 0.0, 0.0),           # T+15:00 re-zeroed
    (1199, 0.0, 0.0),
])
def test_offset_check_values(script, t_s, expected, tol):
    assert offset_at(script.drift, t_s) == pytest.approx(expected, abs=tol if tol else 1e-12)


def test_ramp_is_straight_inside_a_second(script):
    offs = offsets_for_second(script.drift, 534, 125)
    assert offs.shape == (125,)
    assert np.allclose(np.diff(offs), 15.0 / 420 / 125)
    assert np.all(offsets_for_second(script.drift, 899, 125) == 15.0)
    assert np.all(offsets_for_second(script.drift, 900, 125) == 0.0)


def test_drift_only_touches_abp():
    with pytest.raises(ValueError):
        DriftSpec(bed_id="B08", ramp_start_s=300, ramp_end_s=720, hold_end_s=900, peak_mmHg=15.0, channel="ecg")


def _b08(full_run):
    result, bus, _, _ = full_run
    return result, {(m["ts"] - result.origin_ms) // 1000: m for m in bus.by_bed()["B08"]}


@pytest.mark.parametrize("t_s", [0, 299, 300, 450, 534, 666, 719, 720, 899, 900, 1100, 1199])
def test_b08_abp_carries_the_offset(full_run, packs, script, t_s):
    _, msgs = _b08(full_run)
    raw = packs["B08"].wave("abp", t_s)
    expected = round_samples(raw + offsets_for_second(script.drift, t_s, 125), 1)
    assert msgs[t_s]["abp"] == expected
    # sample 0 shows the check value, within the 0.1 mmHg rounding of the arterial line
    measured = msgs[t_s]["abp"][0] - float(raw[0])
    assert measured == pytest.approx(offset_at(script.drift, t_s), abs=0.051)


@pytest.mark.parametrize("t_s", [299, 534, 666, 720, 899, 900])
def test_b08_other_channels_unchanged(full_run, packs, t_s):
    _, msgs = _b08(full_run)
    pack = packs["B08"]
    m = msgs[t_s]
    assert m["ecg"] == round_samples(pack.wave("ecg", t_s), 3)
    assert m["ppg"] == round_samples(pack.wave("ppg", t_s), 2)
    assert m["hr"] == int(pack.numeric("hr", t_s))
    assert m["spo2"] == int(pack.numeric("spo2", t_s))
    assert m["rr"] == int(pack.numeric("rr", t_s))


def test_b08_cuff_unchanged_during_drift(full_run):
    result, msgs = _b08(full_run)
    assert msgs[300]["nibp"]["sys"] == 118 and msgs[600]["nibp"]["sys"] == 121


def test_other_beds_have_no_drift(full_run, packs):
    _, bus, _, _ = full_run
    m = bus.by_bed()["B09"][600]
    assert m["abp"] == round_samples(packs["B09"].wave("abp", 600), 1)
