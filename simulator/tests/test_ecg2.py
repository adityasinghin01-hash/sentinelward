"""doc 00 v1.3: vitals carry ecg2 + ecg_leads only when the bed pack has a second ECG lead."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import sw_common

from conftest import FS, MIMIC, VITALDB, ALARMS, B01_CUFF, B08_CUFF, play, write_pack
from sw_sim.packs import lead_name, load_pack, load_packs


def _add_ecg2(folder: Path, bed: str, ecg_name: str, ecg2_name: str) -> np.ndarray:
    """Add an ecg2 array (with one NaN) and lead names to an existing synthetic pack."""
    with np.load(folder / f"{bed}.npz") as z:
        arrays = {k: z[k] for k in z.files}
    n = arrays["ecg"].size
    ecg2 = (0.5 * np.cos(2 * np.pi * np.arange(n) / FS) + 0.0004).astype("<f4")
    ecg2[290 * FS + 7] = np.nan
    arrays["ecg2"] = ecg2
    np.savez(folder / f"{bed}.npz", **arrays)
    meta = json.loads((folder / f"{bed}.json").read_text())
    meta["channels"] = ["ecg", "ecg2"] + [c for c in meta["channels"] if c != "ecg"]
    meta["source"] = {"channels": {"ecg": {"name": ecg_name}, "ecg2": {"name": ecg2_name}}}
    (folder / f"{bed}.json").write_text(json.dumps(meta))
    return ecg2


@pytest.fixture(scope="module")
def packs_ecg2(tmp_path_factory):
    folder = tmp_path_factory.mktemp("packs_ecg2")
    for n, bed in enumerate(MIMIC):
        write_pack(folder, bed, 1210 if bed == "B12" else 1200, seed=n, cuff=B01_CUFF if bed == "B01" else None)
    for n, bed in enumerate(VITALDB):
        write_pack(folder, bed, 1200, seed=10 + n, cuff=B08_CUFF if bed == "B08" else None)
    write_pack(folder, "B03", 330, seed=20, alarms=[ALARMS["B03"]])
    write_pack(folder, "B04", 330, seed=21, abp=False, alarms=[ALARMS["B04"]])
    write_pack(folder, "B07", 330, seed=22, alarms=[ALARMS["B07"]])
    ecg2 = _add_ecg2(folder, "B03", "II", "V")
    _add_ecg2(folder, "B08", "SNUADC/ECG_II", "SNUADC/ECG_V5")
    return folder, ecg2


@pytest.mark.parametrize("raw,want", [("II", "II"), ("V", "V"), ("SNUADC/ECG_V5", "V5"), ("SNUADC/ECG_II", "II"),
                                      (None, "ECG2"), ("", "ECG2")])
def test_lead_name(raw, want):
    assert lead_name(raw, "ECG2") == want


def test_pack_loader_reads_ecg2_and_lead_names(packs_ecg2):
    folder, ecg2 = packs_ecg2
    p = load_pack(folder, "B03")
    assert p.has("ecg2") and p.ecg_leads == ("II", "V")
    assert load_pack(folder, "B04").ecg_leads == ("ECG",) and not load_pack(folder, "B04").has("ecg2")


def test_vitals_carry_ecg2_only_for_two_lead_packs(packs_ecg2, script, tmp_path):
    folder, ecg2 = packs_ecg2
    packs = load_packs(folder, [b.pack_name for b in script.beds])
    result, bus, _events, _clock = play(script, packs, tmp_path, start_at_s=1190)
    assert bus.validation_errors == []
    by_bed = bus.by_bed()
    for m in by_bed["B08"]:
        assert m["ecg_leads"] == ["II", "V5"] and len(m["ecg2"]) == FS
        assert sw_common.validate(m, strict=True) == []
    for bed in ("B01", "B09", "B12"):
        assert all("ecg2" not in m and "ecg_leads" not in m for m in by_bed[bed])


def test_ecg2_samples_rounded_and_nan_sent_as_null(packs_ecg2, script, tmp_path):
    folder, ecg2 = packs_ecg2
    packs = load_packs(folder, [b.pack_name for b in script.beds])
    # B03 joins at T+00:00 at pack second 0, so T+04:50 plays pack second 290.
    result, bus, _events, _clock = play(script, packs, tmp_path, start_at_s=290)
    msgs = {m["seq"]: m for m in bus.by_bed()["B03"]}
    first = msgs[1]
    assert first["ecg_leads"] == ["II", "V"]
    assert first["ecg2"][7] is None
    want = np.round(ecg2[290 * FS:291 * FS].astype(np.float64), 3)
    got = np.array([np.nan if v is None else v for v in first["ecg2"]])
    np.testing.assert_array_equal(np.isnan(got), np.isnan(want))
    np.testing.assert_allclose(got[~np.isnan(got)], want[~np.isnan(want)], atol=0)
    assert all("ecg2" not in m for m in bus.by_bed()["B04"])
