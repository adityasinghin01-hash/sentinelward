"""VitalDB .vital files (Mac or Colab only): 500 Hz SNUADC waves, 2 s Solar8000 numbers, NIBP cuff."""
from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

import numpy as np

from sw_data import VITAL_ENDIAN_MESSAGE, BedError, EndianError
from sw_data.beds import BedSpec, Paths, SourceData
from sw_data.dsp import (clean_missing, cuff_readings, ecg_to_mv, first_valid_window, flat_mask,
                         per_minute_fractions, rolling_mean, stats_table, to_second_grid, window_resample)

DATASET_LABEL = "VitalDB"
TRACKS: dict[str, list[str]] = {
    "ecg": ["SNUADC/ECG_II", "SNUADC/ECG_V5"],
    "ppg": ["SNUADC/PLETH"],
    "abp": ["SNUADC/ART"],
    "hr": ["Solar8000/HR"],
    "spo2": ["Solar8000/PLETH_SPO2"],
    "rr": ["Solar8000/RR_CO2", "Solar8000/RR"],
    "nibp_sys": ["Solar8000/NIBP_SBP"],
    "nibp_dia": ["Solar8000/NIBP_DBP"],
    "nibp_map": ["Solar8000/NIBP_MBP"],
}
ALL_TRACKS = [t for names in TRACKS.values() for t in names]
WAVE_FS_DEFAULT = 500.0
NUMBER_MAX_AGE_S = 2.0
CUFF_LOOKBACK_S = 3600
LINE_CUFF_LOOKBACK_S = 30
ART_LINE_MIN_MMHG = 20.0      # check's suggested window: ART under this = line not connected / zeroing


def require_little_endian() -> None:
    """Refuse to go on when this machine is big-endian (vitaldb misreads .vital files there)."""
    if sys.byteorder != "little":
        raise EndianError(VITAL_ENDIAN_MESSAGE)


def _vitalfile_class() -> Any:
    try:
        from vitaldb import VitalFile  # imported lazily: not installed on LinuxONE
    except ImportError as exc:
        raise RuntimeError("the vitaldb package is not installed (Mac/Colab: pip install vitaldb==1.7.2)") from exc
    return VitalFile


def open_vital(path: str | Path, track_names: Optional[Sequence[str]] = None) -> Any:
    """Open one of OUR .vital files whole with ``vitaldb.VitalFile`` (never ``load_case``).

    Raises EndianError on big-endian machines before touching the file.
    """
    require_little_endian()
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"VitalDB file not found: {p}")
    cls = _vitalfile_class()
    if track_names:
        return cls(str(p), track_names=list(track_names))
    return cls(str(p))


def find_vital(base: Optional[Path], case: int) -> Path:
    """``<case>.vital`` (or zero-padded) under the VitalDB folder; raises FileNotFoundError."""
    if base is None:
        raise FileNotFoundError("paths.vitaldb is not set in beds.yaml")
    for name in (f"{case}.vital", f"{case:04d}.vital", f"{case:05d}.vital"):
        if (base / name).is_file():
            return base / name
    raise FileNotFoundError(f"VitalDB case {case} not found in {base} (looked for {case}.vital)")


def clinical_row(csv_path: Optional[Path], case: int) -> Optional[dict[str, str]]:
    """Row of clinical_data.csv for ``case`` (None if the file or the case is absent)."""
    if csv_path is None or not Path(csv_path).is_file():
        return None
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            try:
                if int(float(row.get("caseid", ""))) == int(case):
                    return row
            except ValueError:
                continue
    return None


def is_line_case(row: Optional[dict[str, str]]) -> bool:
    """True if the anaesthesia record lists an arterial line (non-empty ``aline1``)."""
    if row is None:
        return False
    v = str(row.get("aline1") or "").strip()
    return v.lower() not in ("", "nan", "none", "0")


def _first(found: set[str], candidates: Sequence[str]) -> Optional[str]:
    for c in candidates:
        if c in found:
            return c
    return None


def _track_attr(vf: Any, name: str, attr: str, default: Any) -> Any:
    trks = getattr(vf, "trks", None)
    try:
        v = getattr(trks[name], attr)
    except (KeyError, TypeError, AttributeError, IndexError):
        return default
    return default if v in (None, "") else v


def _wave(vf: Any, name: str) -> tuple[np.ndarray, float, str]:
    fs = float(_track_attr(vf, name, "srate", WAVE_FS_DEFAULT)) or WAVE_FS_DEFAULT
    arr = np.asarray(vf.to_numpy([name], 1.0 / fs), dtype=np.float64).reshape(-1)
    return clean_missing(arr), fs, str(_track_attr(vf, name, "unit", ""))


def _numbers(vf: Any, found: set[str]) -> dict[str, np.ndarray]:
    """Monitor numbers on a 1 s bin grid from file start (NaN between samples)."""
    names = {k: _first(found, TRACKS[k]) for k in ("hr", "spo2", "rr", "nibp_sys", "nibp_dia", "nibp_map")}
    present = [n for n in names.values() if n is not None]
    if not present:
        return {}
    arr = np.asarray(vf.to_numpy(present, 1.0), dtype=np.float64)
    arr = arr.reshape(arr.shape[0], -1)
    out = {k: clean_missing(arr[:, present.index(n)]) for k, n in names.items() if n is not None}
    out["_names"] = names  # type: ignore[assignment]
    return out


def build_source(spec: BedSpec, paths: Paths) -> SourceData:
    """Read a VitalDB window into pack grids (refuses on big-endian machines)."""
    spec.require("case", "start_min")
    if spec.duration_s is None:
        raise BedError(spec.bed_id, "duration_s not set")
    try:
        require_little_endian()
    except EndianError as exc:
        raise BedError(spec.bed_id, str(exc)) from exc
    try:
        path = find_vital(paths.vitaldb, spec.case)
    except FileNotFoundError as exc:
        raise BedError(spec.bed_id, str(exc)) from exc

    row = clinical_row(paths.vitaldb_clinical, spec.case)
    line_case = is_line_case(row)
    if spec.wants("abp"):
        if paths.vitaldb_clinical is None or not Path(paths.vitaldb_clinical).is_file():
            raise BedError(spec.bed_id, "clinical_data.csv not found (paths.vitaldb_clinical); "
                                        "cannot confirm the arterial line (aline1)")
        if row is None:
            raise BedError(spec.bed_id, f"case {spec.case} not in {paths.vitaldb_clinical}")
        if not line_case:
            raise BedError(spec.bed_id, f"case {spec.case} has no arterial line (aline1 empty); its ART is not usable")
    ref_s = 0.0
    if spec.window_ref == "opstart":
        if row is None or str(row.get("opstart") or "").strip() == "":
            raise BedError(spec.bed_id, f"window_ref opstart but no opstart for case {spec.case}")
        ref_s = float(row["opstart"])
    start_s = ref_s + float(spec.start_min) * 60.0
    dur = int(spec.duration_s)

    try:
        vf = open_vital(path, ALL_TRACKS)
    except (EndianError, FileNotFoundError, RuntimeError) as exc:
        raise BedError(spec.bed_id, str(exc)) from exc
    found = set(vf.get_track_names())
    wave_names = {k: _first(found, TRACKS[k]) for k in ("ecg", "ppg", "abp")}
    lacking = [k for k in ("ecg", "ppg", "abp") if spec.wants(k) and wave_names[k] is None]
    if lacking:
        raise BedError(spec.bed_id, f"case {spec.case} lacks required track(s) "
                                    f"{[TRACKS[k][0] for k in lacking]}; found {sorted(found)}")

    notes: list[str] = []
    waves: dict[str, np.ndarray] = {}
    channels: dict[str, dict[str, Any]] = {}
    originals: list[dict[str, Any]] = []
    for key, name in wave_names.items():
        if name is None:
            continue
        if key == "abp" and not line_case:
            notes.append(f"{name} skipped: case has no arterial line (aline1)")
            continue
        x, fs, unit = _wave(vf, name)
        originals.append({"name": name, "fs": fs, "units": unit})
        n0 = int(round(start_s * fs))
        n = int(round(dur * fs))
        if n0 + n > x.size:
            raise BedError(spec.bed_id, f"case {spec.case} is {x.size / fs / 60:.1f} min long; "
                                        f"window {start_s / 60:.1f}+{dur / 60:.1f} min does not fit")
        if key == "ecg":
            if name != TRACKS["ecg"][0]:
                notes.append(f"ECG lead II absent; used {name}")
            x, note, _warn = ecg_to_mv(x, unit or "mV")
            if note:
                notes.append(note)
            unit = "mV"
        try:
            waves[key] = window_resample(x, fs, n0, n)
        except ValueError as exc:
            raise BedError(spec.bed_id, f"{key}: {exc}") from exc
        channels[key] = {"name": name, "fs": fs, "units": unit}

    nums = _numbers(vf, found)
    num_names = nums.pop("_names", {}) if nums else {}
    grid = {k: np.full(dur, np.nan) for k in ("hr", "spo2", "rr")}
    nibp = np.zeros((0, 4))
    if nums:
        n_sec = next(iter(nums.values())).size
        i0 = max(0, int(start_s) - CUFF_LOOKBACK_S)
        i1 = min(n_sec, int(np.ceil(start_s + dur)) + 1)
        t = np.arange(i0, i1, dtype=np.float64) - start_s
        for k in ("hr", "spo2", "rr"):
            if k in nums:
                grid[k] = to_second_grid(t, nums[k][i0:i1], dur, NUMBER_MAX_AGE_S)
                originals.append({"name": num_names[k], "fs": 0.5, "units": ""})
            else:
                notes.append(f"no {'/'.join(TRACKS[k])} track; {k} is NaN")
        if "nibp_sys" in nums:
            nan = np.full(n_sec, np.nan)
            dia = nums.get("nibp_dia", nan)
            mean = nums.get("nibp_map", nan)
            nibp = cuff_readings(t, nums["nibp_sys"][i0:i1], dia[i0:i1], mean[i0:i1], dur)
            originals += [{"name": num_names[k], "fs": None, "units": "mmHg"}
                          for k in ("nibp_sys", "nibp_dia", "nibp_map") if num_names.get(k)]
    if spec.wants("numbers") and "hr" not in nums:
        raise BedError(spec.bed_id, f"case {spec.case} lacks required track {TRACKS['hr'][0]}")
    cuff_found = "nibp_sys" in nums
    if spec.wants("cuff"):
        if not cuff_found:
            raise BedError(spec.bed_id, f"case {spec.case} lacks required track {TRACKS['nibp_sys'][0]}")
        if nibp.shape[0] == 0:
            raise BedError(spec.bed_id, f"no new cuff reading in the window "
                                        f"{start_s / 60:.1f}-{(start_s + dur) / 60:.1f} min of case {spec.case}")
    if spec.window_ref == "opstart":
        notes.append(f"window counted from opstart ({ref_s:.0f} s into the file)")

    source = {
        "dataset": DATASET_LABEL,
        "case": spec.case,
        "path": str(path),
        "window_ref": spec.window_ref,
        "window_start_s": start_s,
        "window_start_min": start_s / 60.0,
        "aline1": None if row is None else row.get("aline1"),
        "channels": channels,
        "original_channels": originals,
    }
    return SourceData(dataset="vitaldb", duration_s=dur, source=source, waves=waves,
                      hr=grid["hr"], spo2=grid["spo2"], rr=grid["rr"], nibp=nibp, alarms=[],
                      notes=notes, numerics_found="hr" in nums, cuff_found=cuff_found)


# --------------------------------------------------------------------------- check


def line_minus_cuff(art: np.ndarray, fs: float, readings: np.ndarray, t_base_s: float = 0.0) -> float:
    """Median of (line systolic - cuff systolic) over cuff readings.

    Line systolic = median of the per-second ART maxima over the 30 s before each reading.
    ``readings`` rows are ``[t, sys, dia, map]`` with ``t`` in seconds from ``t_base_s`` in ``art``.
    """
    gaps = []
    for t, sys_v, _d, _m in readings:
        end = int(round((t_base_s + t) * fs))
        beg = end - int(LINE_CUFF_LOOKBACK_S * fs)
        if beg < 0 or end > art.size or np.isnan(sys_v):
            continue
        per_s = int(round(fs))
        seg = art[beg:beg + LINE_CUFF_LOOKBACK_S * per_s].reshape(-1, per_s)
        rows = seg[~np.isnan(seg).all(axis=1)]
        if rows.shape[0]:
            gaps.append(float(np.median(np.nanmax(rows, axis=1))) - float(sys_v))
    return float(np.median(gaps)) if gaps else float("nan")


def suggest_window(waves: dict[str, tuple[np.ndarray, float]], hr: Optional[np.ndarray],
                   cuff_t: np.ndarray, minutes: int) -> Optional[int]:
    """First start minute where ECG/PLETH/ART are <5 % missing and <5 % flat, HR <=50 % missing,
    and at least one new cuff reading falls inside the window.

    ART minutes with more than 5 % of samples under ``ART_LINE_MIN_MMHG`` make a window invalid
    (no such minute allowed anywhere in it): before the line is connected VitalDB records a noisy
    -10 to -20 mmHg baseline that is neither missing nor flat (case 4277 minutes 0-9).
    """
    limits = []
    for name, (x, fs) in waves.items():
        miss, flat = per_minute_fractions(x, fs)
        limits += [(miss, 0.05), (flat, 0.05)]
        if name in TRACKS["abp"]:
            per = int(round(60 * fs))
            n_min = x.size // per if per else 0
            if n_min:
                with np.errstate(invalid="ignore"):
                    low = np.nan_to_num(x[:n_min * per], nan=np.inf) < ART_LINE_MIN_MMHG
                limits.append(((low.reshape(n_min, per).mean(axis=1) > 0.05).astype(float), 1e-9))
    if hr is not None:
        n_min = hr.size // 60
        limits.append((np.isnan(hr[:n_min * 60]).reshape(n_min, 60).mean(axis=1), 0.5 + 1e-9))
    if not limits:
        return None
    n = min(a.size for a, _ in limits)
    per_min = np.bincount(np.clip((cuff_t // 60).astype(int), 0, max(n - 1, 0)), minlength=n)[:n] \
        if cuff_t.size else np.zeros(n)
    extra = rolling_mean(per_min, minutes) * minutes >= 1
    return first_valid_window(limits, minutes, extra_ok=extra)


def check_lines(path: Path, start_min: Optional[float] = None, minutes: int = 22,
                clinical: Optional[Path] = None) -> list[str]:
    """One-screen check report for a .vital case, with cuff and line-cuff stats for a window."""
    vf = open_vital(path, ALL_TRACKS)
    found = set(vf.get_track_names())
    lines = [f"== {path.name}  [{DATASET_LABEL}]  {path}"]
    lines.append("  tracks found:   " + (", ".join(t for t in ALL_TRACKS if t in found) or "-"))
    lines.append("  tracks missing: " + (", ".join(t for t in ALL_TRACKS if t not in found) or "-"))
    case = None
    try:
        case = int(path.stem)
    except ValueError:
        pass
    if clinical is not None and case is not None:
        row = clinical_row(clinical, case)
        lines.append(f"  aline1: {row.get('aline1')!r} -> {'LINE CASE' if is_line_case(row) else 'NOT a line case'}"
                     if row is not None else f"  aline1: case {case} not in {clinical}")
    waves: dict[str, tuple[np.ndarray, float]] = {}
    rows = []
    for key in ("ecg", "ppg", "abp"):
        name = _first(found, TRACKS[key])
        if name is None:
            continue
        x, fs, unit = _wave(vf, name)
        waves[name] = (x, fs)
        rows.append((name, fs, unit, x))
    if waves:
        x0, fs0 = next(iter(waves.values()))
        lines.append(f"  length {x0.size / fs0 / 60:.1f} min ({x0.size} samples at {fs0:g} Hz)")
    lines.append("  whole file:")
    lines += stats_table(rows)
    nums = _numbers(vf, found)
    num_names = nums.pop("_names", {}) if nums else {}
    hr = nums.get("hr")
    hr_grid = None
    if hr is not None:
        hr_grid = to_second_grid(np.arange(hr.size, dtype=float), hr, hr.size, NUMBER_MAX_AGE_S)
    readings = np.zeros((0, 4))
    if "nibp_sys" in nums:
        nan = np.full(nums["nibp_sys"].size, np.nan)
        readings = cuff_readings(np.arange(nan.size, dtype=float), nums["nibp_sys"],
                                 nums.get("nibp_dia", nan), nums.get("nibp_map", nan))
    lines.append(f"  cuff readings in file: {readings.shape[0]}")
    sugg = suggest_window(waves, hr_grid, readings[:, 0], minutes)
    lines.append(f"  suggested start: {'none (no window with all signals valid)' if sugg is None else f'minute {sugg}'}"
                 f"  (rule: ECG/PLETH/ART <5 % missing and <5 % flat, no ART minute >5 % under 20 mmHg, HR <=50 % missing, >=1 cuff reading)")
    use = start_min if start_min is not None else sugg
    if use is None:
        return lines
    t0, t1 = float(use) * 60, float(use) * 60 + minutes * 60
    lines.append(f"  window minute {float(use):g}-{float(use) + minutes:g}:")
    wrows = []
    for name, (x, fs) in waves.items():
        a, b = int(t0 * fs), int(t1 * fs)
        wrows.append((name, fs, "", x[a:b]))
    lines += stats_table(wrows)
    for k in ("hr", "spo2", "rr"):
        if k in nums:
            g = to_second_grid(np.arange(nums[k].size, dtype=float) - t0, nums[k], minutes * 60, NUMBER_MAX_AGE_S)
            lines.append(f"  {num_names[k]:<24} missing {100 * np.isnan(g).mean():6.2f} %")
    win = readings[(readings[:, 0] >= t0) & (readings[:, 0] < t1)] if readings.size else readings
    lines.append(f"  cuff readings in window: {win.shape[0]}")
    art_name = _first(found, TRACKS["abp"])
    if art_name is not None and win.shape[0]:
        art, fs = waves[art_name]
        gap = line_minus_cuff(art, fs, win)
        lines.append(f"  median line-minus-cuff systolic gap: {gap:+.1f} mmHg over {win.shape[0]} reading(s)")
    elif art_name is None:
        lines.append("  median line-minus-cuff systolic gap: n/a (no ART track)")
    else:
        lines.append("  median line-minus-cuff systolic gap: n/a (no cuff reading in window)")
    if art_name is not None:
        x, fs = waves[art_name]
        flat_pct = 100 * flat_mask(x[int(t0 * fs):int(t1 * fs)], fs).mean() if x.size else 0.0
        if flat_pct > 5:
            lines.append(f"  WARNING: ART flat {flat_pct:.1f} % in window (junk line signal?)")
    return lines
