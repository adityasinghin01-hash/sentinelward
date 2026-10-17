"""Acceptance checks 4, 6 and 8: 2015 alarms, MIMIC numerics alignment, VitalDB endian guard."""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from conftest import GAP_S, MASTER, PIECE1, PIECE1_S, PIECE2, make_mimic
from sw_data import VITAL_ENDIAN_MESSAGE, BedError, EndianError
from sw_data.beds import BedSpec, Paths
from sw_data import cinc2015, mimic, vital

# ---------------------------------------------------------------- check 4


def test_header_vtach_true_gives_one_high_alarm_at_300() -> None:
    alarm = cinc2015.parse_alarm(["#Ventricular_Tachycardia", "#True alarm"])
    assert alarm == {"t_offset_s": 300, "code": "VTACH", "true_alarm": True, "priority": "high"}


@pytest.mark.parametrize("comment,code,prio", [("Asystole", "ASYSTOLE", "high"), ("Bradycardia", "BRADY", "medium"),
                                               ("Tachycardia", "TACHY", "medium"),
                                               ("Ventricular_Flutter_Fib", "VFIB", "high")])
def test_all_alarm_codes(comment: str, code: str, prio: str) -> None:
    a = cinc2015.parse_alarm([comment, "False alarm"])
    assert (a["code"], a["priority"], a["true_alarm"]) == (code, prio, False)


def test_header_without_label_is_rejected() -> None:
    with pytest.raises(ValueError):
        cinc2015.parse_alarm(["Asystole"])


def test_cinc_record_builds_with_alarm_and_hr(cinc_dir: Path) -> None:
    spec = BedSpec(bed_id="B03", device_id="MON-03", dataset="cinc2015", signals=["ecg", "ppg", "abp"], record="v999l")
    sd = cinc2015.build_source(spec, Paths(cinc2015=cinc_dir))
    assert sd.alarms == [{"t_offset_s": 300, "code": "VTACH", "true_alarm": True, "priority": "high"}]
    assert sd.duration_s == 330
    assert set(sd.waves) == {"ecg", "ppg", "abp"}
    assert all(w.size == 330 * 125 for w in sd.waves.values())
    assert np.all(np.abs(sd.hr[5:] - 75) <= 1)
    assert np.isnan(sd.spo2).all() and np.isnan(sd.rr).all()
    assert sd.nibp.shape == (0, 4)


# ---------------------------------------------------------------- check 6


def test_piece_offset_from_master_header(mimic_root: Path) -> None:
    pdir = mimic.patient_dir(mimic_root, "p000001")
    loc = mimic.locate_piece(pdir, PIECE2)
    assert loc.master.name == MASTER
    assert loc.offset_samples == (PIECE1_S + GAP_S) * 125
    assert loc.offset_s == 15.0
    assert mimic.locate_piece(pdir, PIECE1).offset_s == 0.0


@pytest.mark.parametrize("start_s", [0, 30])
def test_numerics_line_up_with_second_piece(mimic_root: Path, start_s: int) -> None:
    spec = BedSpec(bed_id="B02", device_id="MON-02", dataset="mimic", signals=["ecg", "ppg", "resp", "numerics"],
                   patient="p000001", piece=PIECE2, start_s=start_s, duration_s=300)
    sd = mimic.build_source(spec, Paths(mimic=mimic_root))
    # numerics HR holds the master-record second, so hr[t] must equal 15 + start + t
    # (atol only covers wrsamp's 16-bit quantisation; an offset error would be >= 1)
    np.testing.assert_allclose(sd.hr, 15 + start_s + np.arange(300), atol=0.01)
    assert sd.source["master_offset_s"] == 15.0
    assert set(sd.waves) == {"ecg", "ppg", "resp"}
    master_s = 15 + start_s + np.arange(300)
    expected_spo2 = np.where((master_s >= 20) & (master_s < 25), np.nan, 97.0)  # fixture gap stays NaN
    np.testing.assert_allclose(sd.spo2, expected_spo2, atol=0.01)
    # cuff: 110 at master 5 s is carried into the window (not new); 120 at 60 s and 95 at 200 s are new
    t0 = 15 + start_s
    np.testing.assert_allclose(sd.nibp, [[60 - t0, 120, 75, 90], [200 - t0, 95, 60, 72]], atol=0.01)


def test_numerics_start_delta_is_applied() -> None:
    m = SimpleNamespace(base_date=dt.date(2100, 1, 1), base_time=dt.time(12, 0, 0))
    n = SimpleNamespace(base_date=dt.date(2100, 1, 1), base_time=dt.time(12, 0, 3))
    delta, note = mimic.start_delta_s(m, n)
    assert delta == 3.0 and note
    assert mimic.start_delta_s(m, m) == (0.0, None)


def test_mimic_window_too_long_fails(mimic_root: Path) -> None:
    spec = BedSpec(bed_id="B05", device_id="MON-05", dataset="mimic", signals=["ecg", "ppg"],
                   patient="p000001", piece=PIECE2, start_s=200, duration_s=300)
    with pytest.raises(BedError, match="B05: piece .* does not fit"):
        mimic.build_source(spec, Paths(mimic=mimic_root))


def test_check_piece_reports_line_up(mimic_root: Path) -> None:
    lines = mimic.check_piece(mimic_root / "p00" / "p000001" / PIECE2)
    text = "\n".join(lines)
    assert "numerics line up: YES" in text
    assert "15.000 s" in text


def test_pick_mimic_lists_patients(tmp_path: Path) -> None:
    root = tmp_path / "sample"
    make_mimic(root)
    rows = mimic.pick_mimic(root, exclude=[], need=3, minutes=2, min_hours=0.1)
    assert [r["patient"] for r in rows] == ["p000001"]
    assert rows[0]["piece"] == PIECE2 and rows[0]["start_s"] == 0
    assert mimic.pick_mimic(root, exclude=["p000001"], need=3, minutes=2, min_hours=0.1) == []


# ---------------------------------------------------------------- check 8


def test_big_endian_refuses_vital_with_exact_message(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / "5552.vital"
    f.write_bytes(b"not read")

    def must_not_open() -> None:
        raise AssertionError("vitaldb must not be touched on big-endian")

    monkeypatch.setattr(vital, "_vitalfile_class", must_not_open)
    monkeypatch.setattr(sys, "byteorder", "big")
    with pytest.raises(EndianError) as info:
        vital.open_vital(f)
    assert str(info.value) == VITAL_ENDIAN_MESSAGE
    assert str(info.value) == ("VitalDB files must be converted on a little-endian machine (Mac or Colab); "
                               "vitaldb reads them wrongly on LinuxONE.")


def test_big_endian_vital_bed_fails_with_message(fake_vital: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "byteorder", "big")
    spec = BedSpec(bed_id="B08", device_id="MON-08", dataset="vitaldb", signals=["ecg"], case=5552,
                   start_min=2, duration_s=600)
    with pytest.raises(BedError) as info:
        vital.build_source(spec, Paths(vitaldb=fake_vital, vitaldb_clinical=fake_vital / "clinical_data.csv"))
    assert str(info.value) == f"B08: {VITAL_ENDIAN_MESSAGE}"


def test_vital_bed_from_fake_file(fake_vital: Path) -> None:
    spec = BedSpec(bed_id="B08", device_id="MON-08", dataset="vitaldb",
                   signals=["ecg", "ppg", "abp", "cuff", "numbers"], case=5552, start_min=2, duration_s=600)
    sd = vital.build_source(spec, Paths(vitaldb=fake_vital, vitaldb_clinical=fake_vital / "clinical_data.csv"))
    assert set(sd.waves) == {"ecg", "ppg", "abp"}
    assert all(w.size == 600 * 125 for w in sd.waves.values())
    assert np.all(sd.hr == 66) and np.all(sd.spo2 == 99) and np.all(sd.rr == 12)
    # 118 at 30 s is carried in; 124 at 330 s and 110 at 630 s are new (window starts at 120 s)
    np.testing.assert_array_equal(sd.nibp, [[210, 124, 76, 92], [510, 110, 68, 82]])


def test_vital_without_arterial_line_fails(fake_vital: Path) -> None:
    spec = BedSpec(bed_id="B09", device_id="MON-09", dataset="vitaldb", signals=["ecg", "ppg", "abp"],
                   case=912, start_min=2, duration_s=600)
    with pytest.raises(BedError, match="B09: case 912 has no arterial line"):
        vital.build_source(spec, Paths(vitaldb=fake_vital, vitaldb_clinical=fake_vital / "clinical_data.csv"))


def test_vital_check_suggests_window(fake_vital: Path) -> None:
    lines = vital.check_lines(fake_vital / "5552.vital", minutes=10, clinical=fake_vital / "clinical_data.csv")
    text = "\n".join(lines)
    assert "suggested start: minute 0" in text
    assert "LINE CASE" in text
    assert "cuff readings in window: 2" in text
    # ART peaks at 125 mmHg; cuff 118 and 124 -> gaps +7 and +1 -> median +4
    assert "median line-minus-cuff systolic gap: +4.0 mmHg" in text
