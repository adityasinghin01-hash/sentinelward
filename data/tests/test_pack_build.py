"""Acceptance checks 7 and 9, plus end-to-end build -> verify through the command line."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import yaml

from conftest import PIECE2, make_mimic, write_cinc
from sw_data.beds import load_beds
from sw_data.build import build
from sw_data.cli import main
from sw_data.pack import load_pack, verify_folder, verify_pack, write_pack


def _arrays(duration: int = 10) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(7)
    ecg = rng.normal(size=duration * 125)
    ecg[100:300] = np.nan
    hr = np.full(duration, 72.0)
    hr[3] = np.nan
    return {"ecg": ecg, "hr": hr, "spo2": np.full(duration, np.nan), "rr": np.full(duration, 14.0),
            "nibp": np.array([[2.0, 120.0, 80.0, 93.0]])}


def _meta(bed: str = "B01", duration: int = 10) -> dict:
    return {"bed_id": bed, "device_id": "MON-01", "source": {"dataset": "test"}, "duration_s": duration,
            "alarms": [], "notes": []}


# ---------------------------------------------------------------- check 7


def test_saved_arrays_are_little_endian_f4_and_round_trip(tmp_path: Path) -> None:
    arrays = _arrays()
    write_pack(tmp_path, "B01", arrays, _meta())
    loaded, meta = load_pack(tmp_path, "B01")
    for k, a in arrays.items():
        assert loaded[k].dtype.str == "<f4"
        np.testing.assert_array_equal(loaded[k], a.astype("<f4"))
    assert np.isnan(loaded["ecg"][100:300]).all(), "missing stays NaN, never 0"
    assert meta["byte_order"] == "little" and meta["dtype"] == "<f4" and meta["fs"] == 125
    assert meta["missing_pct"]["ecg"] == pytest.approx(200 / 1250 * 100, abs=1e-3)
    assert verify_pack(tmp_path, "B01") == []


def test_big_endian_input_is_stored_little_endian(tmp_path: Path) -> None:
    arrays = _arrays()
    arrays["ecg"] = arrays["ecg"].astype(">f8")
    write_pack(tmp_path, "B01", arrays, _meta())
    loaded, _ = load_pack(tmp_path, "B01")
    assert loaded["ecg"].dtype.str == "<f4"
    np.testing.assert_array_equal(loaded["ecg"], _arrays()["ecg"].astype("<f4"))


def test_verify_fails_on_changed_byte(tmp_path: Path) -> None:
    write_pack(tmp_path, "B01", _arrays(), _meta())
    npz = tmp_path / "B01.npz"
    raw = bytearray(npz.read_bytes())
    raw[len(raw) // 3] ^= 0x01
    npz.write_bytes(bytes(raw))
    problems = verify_pack(tmp_path, "B01")
    assert problems, "a changed byte must FAIL"


def test_verify_fails_on_changed_array_with_valid_zip(tmp_path: Path) -> None:
    write_pack(tmp_path, "B01", _arrays(), _meta())
    loaded, _ = load_pack(tmp_path, "B01")
    loaded["hr"][0] = 73.0
    with open(tmp_path / "B01.npz", "wb") as fh:
        np.savez(fh, **loaded)
    assert any("hr sha256 mismatch" in p for p in verify_pack(tmp_path, "B01"))


def test_verify_fails_on_wrong_byte_order_label_and_shape(tmp_path: Path) -> None:
    write_pack(tmp_path, "B01", _arrays(), _meta())
    js = tmp_path / "B01.json"
    meta = json.loads(js.read_text())
    meta["byte_order"] = "big"
    meta["duration_s"] = 11
    js.write_text(json.dumps(meta))
    problems = " ".join(verify_pack(tmp_path, "B01"))
    assert "byte-order" in problems and "shape" in problems


# ---------------------------------------------------------------- check 9 and end-to-end


def _beds_yaml(tmp_path: Path, cinc: Path, mimic_root: Path, vit: Path, beds: list[dict]) -> Path:
    doc = {"version": 1,
           "paths": {"cinc2015": str(cinc), "mimic": str(mimic_root), "vitaldb": str(vit),
                     "vitaldb_clinical": str(vit / "clinical_data.csv")},
           "beds": beds}
    p = tmp_path / "beds.yaml"
    p.write_text(yaml.safe_dump(doc, sort_keys=False))
    return p


def test_missing_required_signal_stops_bed_and_writes_nothing(tmp_path: Path, cinc_dir: Path) -> None:
    beds = [{"bed_id": "B03", "device_id": "MON-03", "dataset": "cinc2015", "record": "v999l",
             "signals": ["ecg", "ppg", "abp"]},
            {"bed_id": "B04", "device_id": "MON-04", "dataset": "cinc2015", "record": "n999l",
             "signals": ["ecg", "ppg", "abp"]}]
    y = _beds_yaml(tmp_path, cinc_dir, tmp_path, tmp_path, beds)
    out = tmp_path / "packs"
    msgs: list[str] = []
    results = {r.bed_id: r for r in build(y, out, log=msgs.append)}
    assert results["B03"].ok
    assert not results["B04"].ok
    assert results["B04"].message.startswith("B04: ")
    assert "lacks required signal(s) ['abp']" in results["B04"].message
    assert not (out / "B04.npz").exists() and not (out / "B04.json").exists()
    assert not list(out.glob(".B04*")), "no temporary files left behind"
    assert any(m.startswith("FAIL B04:") for m in msgs)
    summary = (out / "summary.md").read_text()
    assert "| B03 |" in summary and "FAIL" in summary.split("| B04 |")[1]


def test_required_signal_over_half_missing_stops_bed(tmp_path: Path) -> None:
    root = tmp_path / "mimic"
    make_mimic(root, ppg_missing_from_s=100)
    beds = [{"bed_id": "B05", "device_id": "MON-05", "dataset": "mimic", "patient": "p000001",
             "piece": PIECE2, "start_s": 0, "duration_s": 300, "signals": ["ecg", "ppg", "numerics"]}]
    y = _beds_yaml(tmp_path, tmp_path, root, tmp_path, beds)
    r = build(y, tmp_path / "packs", log=lambda m: None)[0]
    assert not r.ok and "B05: required signal ppg (PLETH) is 66.7 % missing" in r.message
    assert not (tmp_path / "packs" / "B05.npz").exists()


def test_unfilled_h1_pick_fails_loudly(tmp_path: Path, mimic_root: Path) -> None:
    beds = [{"bed_id": "B06", "device_id": "MON-06", "dataset": "mimic", "patient": None, "piece": None,
             "start_s": None, "duration_s": 1320, "signals": ["ecg", "ppg", "numerics"]}]
    y = _beds_yaml(tmp_path, tmp_path, mimic_root, tmp_path, beds)
    r = build(y, tmp_path / "packs", log=lambda m: None)[0]
    assert not r.ok and "B06: patient, piece, start_s not filled in; H1 PICK" in r.message


def test_same_patient_on_two_beds_is_rejected(tmp_path: Path) -> None:
    beds = [{"bed_id": f"B0{i}", "dataset": "mimic", "patient": "p000001", "piece": PIECE2, "start_s": 0,
             "duration_s": 60, "signals": ["ecg"]} for i in (1, 2)]
    y = _beds_yaml(tmp_path, tmp_path, tmp_path, tmp_path, beds)
    with pytest.raises(ValueError, match="already used by B01"):
        load_beds(y)


def test_unquoted_piece_name_is_rejected(tmp_path: Path) -> None:
    y = tmp_path / "beds.yaml"
    y.write_text("beds:\n  - bed_id: B01\n    dataset: mimic\n    patient: p000109\n    piece: 3346682_0014\n"
                 "    start_s: 0\n    duration_s: 60\n    signals: [ecg]\n")
    with pytest.raises(ValueError, match="B01: piece must be a quoted name"):
        load_beds(y)


def test_project_beds_yaml_is_valid() -> None:
    paths, specs = load_beds(Path(__file__).resolve().parents[1] / "beds.yaml")
    assert [s.bed_id for s in specs] == [f"B{i:02d}" for i in range(1, 13)]
    assert [s.device_id for s in specs] == [f"MON-{i:02d}" for i in range(1, 13)]
    by = {s.bed_id: s for s in specs}
    # B01: doc 12 named 3346682_0014; only p000109's 3407610 piece is on the server (deploy/SETUP.md)
    assert (by["B01"].piece, by["B02"].piece, by["B05"].piece) == ("3407610_0006", "3533390_0011", "3860035_0044")
    assert by["B01"].start_s == 7200 and by["B08"].start_min == 231 and by["B09"].start_min == 38
    # H1 values filled 17 Oct
    assert by["B10"].case == 4277 and by["B10"].start_min == 12 and by["B10"].backup_case == 5659
    picks = {b: (by[b].patient, by[b].piece, by[b].start_s) for b in ("B06", "B11", "B12")}
    assert picks == {"B06": ("p000154", "3783784_0006", 0), "B11": ("p000160", "3531764_0003", 0),
                     "B12": ("p000298", "3129212_0016", 0)}


def test_full_build_then_verify_via_cli(tmp_path: Path, cinc_dir: Path, mimic_root: Path, fake_vital: Path,
                                        capsys: pytest.CaptureFixture[str]) -> None:
    beds = [
        {"bed_id": "B02", "device_id": "MON-02", "dataset": "mimic", "patient": "p000001", "piece": PIECE2,
         "start_s": 0, "duration_s": 300, "signals": ["ecg", "ppg", "resp", "numerics"]},
        {"bed_id": "B03", "device_id": "MON-03", "dataset": "cinc2015", "record": "v999l",
         "signals": ["ecg", "ppg", "abp"]},
        {"bed_id": "B08", "device_id": "MON-08", "dataset": "vitaldb", "case": 5552, "window_ref": "file",
         "start_min": 2, "duration_s": 600, "signals": ["ecg", "ppg", "abp", "cuff", "numbers"]},
    ]
    y = _beds_yaml(tmp_path, cinc_dir, mimic_root, fake_vital, beds)
    out = tmp_path / "packs"
    assert main(["build", str(y), "--out", str(out), "--beds", "B02,B03"]) == 0
    assert main(["build", str(y), "--out", str(out), "--beds", "B08"]) == 0
    capsys.readouterr()
    assert main(["verify", str(out)]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines == ["B02 PASS", "B03 PASS", "B08 PASS"]

    summary = (out / "summary.md").read_text().splitlines()
    assert sum(1 for l in summary if l.startswith("| B")) == 3, "summary keeps rows across partial builds"

    arrays, meta = load_pack(out, "B03")
    assert set(arrays) == {"ecg", "ppg", "abp", "hr", "spo2", "rr", "nibp"}
    assert arrays["ecg"].shape == (330 * 125,) and arrays["nibp"].shape == (0, 4)
    assert meta["alarms"] == [{"t_offset_s": 300, "code": "VTACH", "true_alarm": True, "priority": "high"}]
    assert meta["source"]["channels"]["ecg"] == {"name": "II", "fs": 250.0, "units": "mV"}
    assert set(meta["sha256"]) == set(arrays)

    arrays, meta = load_pack(out, "B08")
    assert meta["device_id"] == "MON-08" and meta["duration_s"] == 600
    assert arrays["nibp"].shape == (2, 4) and meta["source"]["window_start_s"] == 120.0

    arrays, meta = load_pack(out, "B02")
    assert "resp" in arrays and meta["source"]["master_offset_s"] == 15.0

    assert all(not p for _, p in verify_folder(out))


def test_check_command_runs_on_each_dataset(tmp_path: Path, cinc_dir: Path, mimic_root: Path, fake_vital: Path,
                                            capsys: pytest.CaptureFixture[str]) -> None:
    paths = [str(cinc_dir / "v999l.hea"), str(mimic_root / "p00" / "p000001" / PIECE2),
             str(mimic_root / "p00" / "p000001"), str(fake_vital / "5552.vital")]
    rc = main(["check", *paths, "--minutes", "10", "--clinical", str(fake_vital / "clinical_data.csv")])
    text = capsys.readouterr().out
    assert rc == 0, text
    assert "alarm VTACH  TRUE alarm  priority high" in text
    assert "numerics line up: YES" in text
    assert "suggested start: minute 0" in text


def test_cinc_record_with_short_length_builds_whole(tmp_path: Path) -> None:
    d = tmp_path / "cinc"
    write_cinc(d, "s999s", ["Tachycardia", "True alarm"], seconds=300)
    beds = [{"bed_id": "B07", "dataset": "cinc2015", "record": "s999s", "signals": ["ecg"]}]
    y = _beds_yaml(tmp_path, d, tmp_path, tmp_path, beds)
    r = build(y, tmp_path / "packs", log=lambda m: None)[0]
    assert r.ok, r.message
    arrays, meta = load_pack(tmp_path / "packs", "B07")
    assert arrays["hr"].shape == (300,) and meta["alarms"][0]["priority"] == "medium"
