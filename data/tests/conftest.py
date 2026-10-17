"""Offline fixtures: synthetic WFDB records, a tiny MIMIC sample tree and a fake vitaldb.VitalFile."""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import numpy as np
import pytest
import wfdb

FS_2015 = 250
FS_MIMIC = 125


def spike_ecg(n: int, fs: float, bpm: float, amp: float = 1.0, noise: float = 0.01, seed: int = 0) -> np.ndarray:
    """Gaussian-spike ECG stand-in at ``bpm`` beats/min (mV)."""
    rng = np.random.default_rng(seed)
    t = np.arange(n) / fs
    x = rng.normal(0.0, noise, n)
    period = 60.0 / bpm
    for bt in np.arange(0.3, n / fs, period):
        lo, hi = int((bt - 0.06) * fs), int((bt + 0.06) * fs) + 1
        seg = slice(max(lo, 0), min(hi, n))
        x[seg] += amp * np.exp(-0.5 * ((t[seg] - bt) / 0.012) ** 2)
    return x


def write_record(folder: Path, name: str, fs: float, sig_names: list[str], units: list[str],
                 data: np.ndarray, comments: Optional[list[str]] = None,
                 base_time: Optional[dt.time] = None, base_date: Optional[dt.date] = None) -> Path:
    """Write a WFDB record with wfdb.wrsamp; returns its stem path."""
    folder.mkdir(parents=True, exist_ok=True)
    kwargs = {}
    if base_time is not None:
        kwargs["base_time"] = base_time
    if base_date is not None:
        kwargs["base_date"] = base_date
    wfdb.wrsamp(name, fs=fs, units=units, sig_name=sig_names, p_signal=np.asarray(data, dtype=np.float64),
                fmt=["16"] * len(sig_names), comments=comments, write_dir=str(folder), **kwargs)
    return folder / name


def write_cinc(folder: Path, name: str, comments: list[str], with_abp: bool = True, seconds: int = 330) -> Path:
    """A 2015-style record: II at 75 bpm, PLETH, optionally ABP, 250 Hz."""
    n = seconds * FS_2015
    t = np.arange(n) / FS_2015
    cols = [spike_ecg(n, FS_2015, 75.0), 1.0 + 0.5 * np.sin(2 * np.pi * 1.25 * t)]
    names, units = ["II", "PLETH"], ["mV", "NU"]
    if with_abp:
        cols.append(100.0 + 20.0 * np.sin(2 * np.pi * 1.25 * t))
        names.append("ABP")
        units.append("mmHg")
    return write_record(folder, name, FS_2015, names, units, np.column_stack(cols), comments=comments)


@pytest.fixture
def cinc_dir(tmp_path: Path) -> Path:
    """Folder with v999l (true VT, II/PLETH/ABP) and n999l (no ABP)."""
    d = tmp_path / "cinc"
    write_cinc(d, "v999l", ["Ventricular_Tachycardia", "True alarm"])
    write_cinc(d, "n999l", ["Asystole", "False alarm"], with_abp=False)
    return d


MASTER = "p000001-2100-01-01-00-00"
PIECE1, PIECE2 = "3000001_0001", "3000001_0002"
PIECE1_S, GAP_S, PIECE2_S = 10, 5, 400


def make_mimic(root: Path, ppg_missing_from_s: Optional[int] = None) -> Path:
    """A one-patient MIMIC tree: master = [layout, piece1 10 s, gap 5 s, piece2 400 s] + 1 Hz numerics.

    Numerics HR is the master-record second (0, 1, 2 ...), so alignment can be read off directly.
    """
    pdir = root / "p00" / "p000001"
    pdir.mkdir(parents=True, exist_ok=True)
    base_t, base_d = dt.time(12, 0, 0), dt.date(2100, 1, 1)
    for name, secs in ((PIECE1, PIECE1_S), (PIECE2, PIECE2_S)):
        n = secs * FS_MIMIC
        t = np.arange(n) / FS_MIMIC
        ppg = 1.0 + 0.5 * np.sin(2 * np.pi * 1.2 * t)
        if ppg_missing_from_s is not None and name == PIECE2:
            ppg[ppg_missing_from_s * FS_MIMIC:] = np.nan
        data = np.column_stack([spike_ecg(n, FS_MIMIC, 72.0), ppg, 0.5 * np.sin(2 * np.pi * 0.25 * t)])
        write_record(pdir, name, FS_MIMIC, ["II", "PLETH", "RESP"], ["mV", "NU", "NU"], data)
    total = (PIECE1_S + GAP_S + PIECE2_S) * FS_MIMIC
    (pdir / "3000001_layout.hea").write_text(f"3000001_layout 3 {FS_MIMIC} 0\n~ 0 1 0 II\n~ 0 1 0 PLETH\n~ 0 1 0 RESP\n")
    (pdir / f"{MASTER}.hea").write_text(
        f"{MASTER}/4 3 {FS_MIMIC} {total} 12:00:00.000 01/01/2100\n"
        f"3000001_layout 0\n{PIECE1} {PIECE1_S * FS_MIMIC}\n~ {GAP_S * FS_MIMIC}\n{PIECE2} {PIECE2_S * FS_MIMIC}\n")
    secs = PIECE1_S + GAP_S + PIECE2_S
    hr = np.arange(secs, dtype=float)
    spo2 = np.full(secs, 97.0)
    spo2[20:25] = np.nan
    resp = np.full(secs, 16.0)
    sys_ = np.full(secs, np.nan)
    dia = np.full(secs, np.nan)
    mean = np.full(secs, np.nan)
    for t0, (s, d, m) in ((5, (110, 70, 83)), (60, (120, 75, 90)), (200, (95, 60, 72))):
        sys_[t0:] = s
        dia[t0:] = d
        mean[t0:] = m
    write_record(pdir, f"{MASTER}n", 1, ["HR", "SpO2", "RESP", "NBP Sys", "NBP Dias", "NBP Mean"],
                 ["bpm", "%", "bpm", "mmHg", "mmHg", "mmHg"], np.column_stack([hr, spo2, resp, sys_, dia, mean]),
                 base_time=base_t, base_date=base_d)
    return pdir


@pytest.fixture
def mimic_root(tmp_path: Path) -> Path:
    root = tmp_path / "mimic"
    make_mimic(root)
    return root


# --------------------------------------------------------------------------- fake VitalDB

VITAL_SECONDS = 1200
VITAL_FS = 500


def fake_vital_tracks(seconds: int = VITAL_SECONDS) -> dict[str, tuple[float, np.ndarray, str]]:
    """Track name -> (srate, values, unit). Numbers are on a 1 s grid with NaN on odd seconds (2 s data)."""
    n = seconds * VITAL_FS
    t = np.arange(n) / VITAL_FS
    two_s = np.full(seconds, np.nan)
    two_s[::2] = 1.0
    sbp = np.full(seconds, np.nan)
    dbp = np.full(seconds, np.nan)
    mbp = np.full(seconds, np.nan)
    for t0, (s, d, m) in ((30, (118, 72, 87)), (330, (124, 76, 92)), (630, (110, 68, 82))):
        sbp[t0:] = s
        dbp[t0:] = d
        mbp[t0:] = m
    mask = np.isnan(two_s)
    for a in (sbp, dbp, mbp):
        a[mask] = np.nan
    return {
        "SNUADC/ECG_II": (VITAL_FS, spike_ecg(n, VITAL_FS, 66.0), "mV"),
        "SNUADC/PLETH": (VITAL_FS, 50 + 20 * np.sin(2 * np.pi * 1.1 * t), ""),
        "SNUADC/ART": (VITAL_FS, 95 + 30 * np.sin(2 * np.pi * 1.1 * t), "mmHg"),
        "Solar8000/HR": (0, 66 * two_s, "/min"),
        "Solar8000/PLETH_SPO2": (0, 99 * two_s, "%"),
        "Solar8000/RR_CO2": (0, 12 * two_s, "/min"),
        "Solar8000/NIBP_SBP": (0, sbp, "mmHg"),
        "Solar8000/NIBP_DBP": (0, dbp, "mmHg"),
        "Solar8000/NIBP_MBP": (0, mbp, "mmHg"),
    }


class FakeVitalFile:
    """Stands in for vitaldb.VitalFile: get_track_names(), to_numpy(names, interval), trks."""

    tracks: dict[str, tuple[float, np.ndarray, str]] = {}

    def __init__(self, path: str, track_names: Optional[list[str]] = None) -> None:
        self.path = path
        names = [n for n in self.tracks if track_names is None or n in track_names]
        self._tracks = {n: self.tracks[n] for n in names}
        self.trks = {n: SimpleNamespace(srate=sr, unit=u) for n, (sr, _v, u) in self._tracks.items()}

    def get_track_names(self) -> list[str]:
        return list(self._tracks)

    def to_numpy(self, track_names: list[str], interval: float) -> np.ndarray:
        cols = []
        n_sec = VITAL_SECONDS
        n = int(round(n_sec / interval))
        for name in track_names:
            if name not in self._tracks:
                cols.append(np.full(n, np.nan))
                continue
            sr, vals, _u = self._tracks[name]
            if sr > 0:
                assert abs(interval - 1.0 / sr) < 1e-12, "fake only serves waves at their own rate"
                cols.append(vals.astype(np.float32))
            else:
                assert interval == 1.0, "fake only serves numbers at 1 s"
                cols.append(vals.astype(np.float32))
        return np.column_stack(cols)


@pytest.fixture
def fake_vital(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A VitalDB folder with case 5552 (empty placeholder file) served by FakeVitalFile, plus clinical_data.csv."""
    from sw_data import vital

    d = tmp_path / "vitaldb"
    d.mkdir()
    (d / "5552.vital").write_bytes(b"fake")
    (d / "912.vital").write_bytes(b"fake")
    (d / "clinical_data.csv").write_text("caseid,opstart,aline1\n5552,600,Radial\n912,300,\n")
    FakeVitalFile.tracks = fake_vital_tracks()
    monkeypatch.setattr(vital, "_vitalfile_class", lambda: FakeVitalFile)
    return d
