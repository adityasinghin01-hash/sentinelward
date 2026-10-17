"""v1.3: the loader keeps a second ECG lead (lead V, else the next ECG lead) as optional ``ecg2``."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

from conftest import FS_2015, FS_MIMIC, PIECE2, VITAL_FS, FakeVitalFile, fake_vital_tracks, spike_ecg, write_record
from sw_data.beds import BedSpec, Paths
from sw_data.build import assemble
from sw_data.dsp import pick_ecg, pick_ecg2
from sw_data.pack import load_pack, verify_pack, write_pack
from sw_data import cinc2015, mimic, vital

# VitalDB is read on little-endian machines only (sw_data refuses .vital files on LinuxONE by design).
little_endian_only = pytest.mark.skipif(sys.byteorder != "little", reason="VitalDB beds build on Mac/Colab only")


@pytest.mark.parametrize("names,want", [
    (["II", "V", "PLETH"], 1),            # 2015 usual layout
    (["II", "aVR", "V", "PLETH"], 2),     # lead V preferred over the next lead
    (["I", "II", "III", "PLETH"], 0),     # no V: next ECG lead in channel order (I)
    (["II", "III", "ABP"], 1),
    (["III", "V", "PLETH"], 1),           # no II: main lead III, second V
    (["II", "PLETH", "ABP"], None),       # one lead only
    (["PLETH"], None),
])
def test_pick_ecg2_rule(names, want):
    first, _ = pick_ecg(names)
    idx, _note = pick_ecg2(names, first)
    assert idx == want
    assert idx is None or idx != first


def _cinc_two_lead(folder: Path, name: str, second: np.ndarray | None) -> None:
    n = 330 * FS_2015
    t = np.arange(n) / FS_2015
    cols = [spike_ecg(n, FS_2015, 75.0), 0.5 * spike_ecg(n, FS_2015, 75.0, seed=1), 1.0 + 0.5 * np.sin(2 * np.pi * 1.25 * t)]
    if second is not None:
        cols[1] = second
    write_record(folder, name, FS_2015, ["II", "V", "PLETH"], ["mV", "mV", "NU"], np.column_stack(cols),
                 comments=["Ventricular_Tachycardia", "True alarm"])


def test_cinc_keeps_lead_v_as_ecg2_and_pack_round_trips(tmp_path: Path) -> None:
    d = tmp_path / "cinc"
    _cinc_two_lead(d, "v998l", None)
    spec = BedSpec(bed_id="B03", device_id="MON-03", dataset="cinc2015", signals=["ecg", "ppg"], record="v998l")
    sd = cinc2015.build_source(spec, Paths(cinc2015=d))
    assert set(sd.waves) == {"ecg", "ecg2", "ppg"}
    assert sd.waves["ecg2"].size == 330 * 125
    assert sd.source["channels"]["ecg2"]["name"] == "V" and sd.source["channels"]["ecg"]["name"] == "II"
    assert 0.3 < np.nanmax(sd.waves["ecg2"]) < 0.7          # lead V is the half-amplitude lead
    arrays, meta = assemble(spec, sd)
    write_pack(tmp_path / "packs", "B03", arrays, meta)
    assert verify_pack(tmp_path / "packs", "B03") == []
    loaded, js = load_pack(tmp_path / "packs", "B03")
    assert loaded["ecg2"].dtype.str == "<f4" and "ecg2" in js["channels"] and "ecg2" in js["sha256"]


def test_cinc_without_second_lead_has_no_ecg2(cinc_dir: Path) -> None:
    spec = BedSpec(bed_id="B03", device_id="MON-03", dataset="cinc2015", signals=["ecg"], record="v999l")
    sd = cinc2015.build_source(spec, Paths(cinc2015=cinc_dir))
    assert "ecg2" not in sd.waves


def test_mimic_keeps_second_lead(tmp_path: Path) -> None:
    from conftest import make_mimic
    pdir = make_mimic(tmp_path / "mimic")
    # rewrite piece 2 with II, V, PLETH, RESP (same length, so the master header still fits)
    n = 400 * FS_MIMIC
    t = np.arange(n) / FS_MIMIC
    data = np.column_stack([spike_ecg(n, FS_MIMIC, 72.0), 0.4 * spike_ecg(n, FS_MIMIC, 72.0, seed=3),
                            1.0 + 0.5 * np.sin(2 * np.pi * 1.2 * t), 0.5 * np.sin(2 * np.pi * 0.25 * t)])
    write_record(pdir, PIECE2, FS_MIMIC, ["II", "V", "PLETH", "RESP"], ["mV", "mV", "NU", "NU"], data)
    spec = BedSpec(bed_id="B02", device_id="MON-02", dataset="mimic", signals=["ecg", "ppg", "numerics"],
                   patient="p000001", piece=PIECE2, start_s=0, duration_s=300)
    sd = mimic.build_source(spec, Paths(mimic=tmp_path / "mimic"))
    assert set(sd.waves) == {"ecg", "ecg2", "ppg"}
    assert sd.source["channels"]["ecg2"]["name"] == "V"
    np.testing.assert_allclose(sd.waves["ecg2"], data[:300 * FS_MIMIC, 1], atol=1e-3)


def test_mimic_one_lead_has_no_ecg2(mimic_root: Path) -> None:
    spec = BedSpec(bed_id="B02", device_id="MON-02", dataset="mimic", signals=["ecg", "ppg"],
                   patient="p000001", piece=PIECE2, start_s=0, duration_s=300)
    assert "ecg2" not in mimic.build_source(spec, Paths(mimic=mimic_root)).waves


@little_endian_only
def test_vital_keeps_v5_as_ecg2(fake_vital: Path) -> None:
    tracks = fake_vital_tracks()
    n = len(tracks["SNUADC/ECG_II"][1])
    tracks["SNUADC/ECG_V5"] = (VITAL_FS, 0.3 * spike_ecg(n, VITAL_FS, 66.0, seed=5), "mV")
    FakeVitalFile.tracks = tracks
    spec = BedSpec(bed_id="B08", device_id="MON-08", dataset="vitaldb",
                   signals=["ecg", "ppg", "abp", "cuff", "numbers"], case=5552, start_min=2, duration_s=600)
    sd = vital.build_source(spec, Paths(vitaldb=fake_vital, vitaldb_clinical=fake_vital / "clinical_data.csv"))
    assert set(sd.waves) == {"ecg", "ecg2", "ppg", "abp"}
    assert sd.source["channels"]["ecg2"]["name"] == "SNUADC/ECG_V5"
    assert sd.waves["ecg2"].size == 600 * 125


@little_endian_only
def test_vital_without_v5_has_no_ecg2(fake_vital: Path) -> None:
    spec = BedSpec(bed_id="B08", device_id="MON-08", dataset="vitaldb", signals=["ecg"], case=5552,
                   start_min=2, duration_s=600)
    sd = vital.build_source(spec, Paths(vitaldb=fake_vital, vitaldb_clinical=fake_vital / "clinical_data.csv"))
    assert "ecg2" not in sd.waves


@little_endian_only
def test_vital_empty_v5_is_left_out(fake_vital: Path) -> None:
    tracks = fake_vital_tracks()
    tracks["SNUADC/ECG_V5"] = (VITAL_FS, np.full(len(tracks["SNUADC/ECG_II"][1]), np.nan), "mV")
    FakeVitalFile.tracks = tracks
    spec = BedSpec(bed_id="B08", device_id="MON-08", dataset="vitaldb", signals=["ecg"], case=5552,
                   start_min=2, duration_s=600)
    sd = vital.build_source(spec, Paths(vitaldb=fake_vital, vitaldb_clinical=fake_vital / "clinical_data.csv"))
    assert "ecg2" not in sd.waves and any("ecg2 left out" in n for n in sd.notes)
