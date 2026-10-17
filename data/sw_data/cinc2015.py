"""PhysioNet/CinC 2015 ICU false-alarm challenge records (250 Hz, alarm at 300 s)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Sequence

import numpy as np
import wfdb

from sw_data import ALARM_CODES, ALARM_PRIORITY, CINC_ALARM_T_S, FS_OUT, BedError
from sw_data.beats import hr_from_ecg
from sw_data.beds import BedSpec, Paths, SourceData
from sw_data.dsp import clean_missing, ecg_to_mv, pick_channel, pick_ecg, stats_table, window_resample

DATASET_LABEL = "PhysioNet/CinC 2015"


def record_stem(base: Optional[Path], record: str) -> Path:
    """Path of a record without extension; ``record`` may be a name, a stem or a .hea/.dat path."""
    p = Path(record)
    if p.suffix in (".hea", ".dat"):
        p = p.with_suffix("")
    if not p.is_absolute() and base is not None and not p.with_name(p.name + ".hea").exists():
        p = base / p
    return p


def parse_alarm(comments: Sequence[str]) -> dict[str, Any]:
    """One alarm ``{t_offset_s: 300, code, true_alarm, priority}`` from 2015 header comments.

    Raises ValueError if the alarm type or the true/false label is not found.
    """
    code: Optional[str] = None
    label: Optional[bool] = None
    for raw in comments:
        c = str(raw).strip().lstrip("#").strip()
        if c in ALARM_CODES and code is None:
            code = ALARM_CODES[c]
        low = c.lower()
        if low == "true alarm":
            label = True
        elif low == "false alarm":
            label = False
    if code is None:
        raise ValueError(f"no alarm type in header comments {list(comments)!r} "
                         f"(expected one of {sorted(ALARM_CODES)})")
    if label is None:
        raise ValueError(f"no 'True alarm' / 'False alarm' label in header comments {list(comments)!r}")
    return {"t_offset_s": CINC_ALARM_T_S, "code": code, "true_alarm": label, "priority": ALARM_PRIORITY[code]}


def _picks(names: list[str], want_resp: bool) -> tuple[dict[str, Optional[int]], str]:
    ecg_idx, ecg_note = pick_ecg(names)
    picks = {
        "ecg": ecg_idx,
        "ppg": pick_channel(names, ["PLETH"]),
        "abp": pick_channel(names, ["ABP", "ART"]),
    }
    if want_resp:
        picks["resp"] = pick_channel(names, ["RESP"])
    return picks, ecg_note


def build_source(spec: BedSpec, paths: Paths) -> SourceData:
    """Read a whole 2015 record into pack grids: waveforms at 125 Hz, HR from the ECG, one alarm."""
    spec.require("record")
    stem = record_stem(paths.cinc2015, spec.record)
    if not stem.with_name(stem.name + ".hea").is_file():
        raise BedError(spec.bed_id, f"2015 record not found: {stem}.hea")
    try:
        rec = wfdb.rdrecord(str(stem))
    except Exception as exc:  # wfdb raises many types for damaged files
        raise BedError(spec.bed_id, f"cannot read 2015 record {stem}: {exc}") from exc
    try:
        alarm = parse_alarm(rec.comments or [])
    except ValueError as exc:
        raise BedError(spec.bed_id, f"record {spec.record}: {exc}") from exc

    fs = float(rec.fs)
    names = [str(n) for n in rec.sig_name]
    units = [str(u) for u in rec.units]
    rec_len_s = rec.sig_len / fs
    duration = int(rec.sig_len // fs)
    if spec.duration_s is not None:
        if spec.duration_s > duration:
            raise BedError(spec.bed_id, f"record {spec.record} is {rec_len_s:.1f} s long; "
                                        f"duration_s {spec.duration_s} does not fit")
        duration = spec.duration_s
    if duration < 1:
        raise BedError(spec.bed_id, f"record {spec.record} is too short ({rec_len_s:.2f} s)")

    picks, ecg_note = _picks(names, spec.wants("resp"))
    lacking = [k for k in ("ecg", "ppg", "abp", "resp") if spec.wants(k) and picks.get(k) is None]
    if lacking:
        raise BedError(spec.bed_id, f"record {spec.record} lacks required signal(s) {lacking}; it has {names}")

    n = int(round(duration * fs))
    notes: list[str] = []
    waves: dict[str, np.ndarray] = {}
    channels: dict[str, dict[str, Any]] = {}
    for key, idx in picks.items():
        if idx is None:
            continue
        x = clean_missing(rec.p_signal[:, idx])
        unit = units[idx]
        if key == "ecg":
            notes.append(ecg_note)
            x, note, _warn = ecg_to_mv(x, unit)
            if note:
                notes.append(note)
                if unit.strip().lower() in {"uv", "µv", "μv"}:
                    unit = "mV"
        try:
            waves[key] = window_resample(x, fs, 0, n)
        except ValueError as exc:
            raise BedError(spec.bed_id, f"{key}: {exc}") from exc
        channels[key] = {"name": names[idx], "fs": fs, "units": unit}

    if "ecg" in waves:
        hr = hr_from_ecg(waves["ecg"], FS_OUT, duration)
        notes.append("HR from ECG beat detection (no numerics in 2015 records)")
    else:
        hr = np.full(duration, np.nan)
        notes.append("no ECG; HR is NaN")
    notes.append("2015 records store no SpO2 or breathing rate; spo2 and rr are NaN")
    if duration <= CINC_ALARM_T_S:
        notes.append(f"alarm at {CINC_ALARM_T_S} s is at the end of this {duration} s record")

    source = {
        "dataset": DATASET_LABEL,
        "record": spec.record,
        "path": str(stem),
        "window": "whole record",
        "window_start_s": 0,
        "record_length_s": rec_len_s,
        "channels": channels,
        "original_channels": [{"name": nm, "fs": fs, "units": u} for nm, u in zip(names, units)],
    }
    return SourceData(
        dataset="cinc2015",
        duration_s=duration,
        source=source,
        waves=waves,
        hr=hr,
        spo2=np.full(duration, np.nan),
        rr=np.full(duration, np.nan),
        nibp=np.zeros((0, 4)),
        alarms=[alarm],
        notes=notes,
    )


def is_cinc_record(header: Any) -> bool:
    """True if a wfdb header carries a 2015 alarm comment."""
    try:
        parse_alarm(getattr(header, "comments", None) or [])
        return True
    except ValueError:
        return False


def check_lines(stem: Path) -> list[str]:
    """One-screen check report for a 2015 record."""
    rec = wfdb.rdrecord(str(stem))
    fs = float(rec.fs)
    names = [str(n) for n in rec.sig_name]
    lines = [f"== {stem.name}  [{DATASET_LABEL}]  {stem}",
             f"  length {rec.sig_len / fs:.1f} s ({rec.sig_len} samples at {fs:g} Hz)"]
    try:
        a = parse_alarm(rec.comments or [])
        lines.append(f"  alarm {a['code']}  {'TRUE' if a['true_alarm'] else 'FALSE'} alarm  "
                     f"priority {a['priority']}  at t={a['t_offset_s']} s")
    except ValueError as exc:
        lines.append(f"  ALARM PROBLEM: {exc}")
    lines += stats_table([(nm, fs, u, clean_missing(rec.p_signal[:, i]))
                          for i, (nm, u) in enumerate(zip(names, rec.units))])
    picks, ecg_note = _picks(names, want_resp=False)
    lines.append(f"  pack: ecg={names[picks['ecg']] if picks['ecg'] is not None else '-'}  "
                 f"ppg={names[picks['ppg']] if picks['ppg'] is not None else '-'}  "
                 f"abp={names[picks['abp']] if picks['abp'] is not None else '-'}   ({ecg_note})")
    if picks["ecg"] is not None:
        idx = picks["ecg"]
        x, note, warn = ecg_to_mv(clean_missing(rec.p_signal[:, idx]), rec.units[idx])
        if warn:
            lines.append(f"  WARNING: {note}")
        dur = int(rec.sig_len // fs)
        ecg125 = window_resample(x, fs, 0, int(round(dur * fs)))
        hr = hr_from_ecg(ecg125, FS_OUT, dur)
        fin = hr[np.isfinite(hr)]
        last = hr[max(0, CINC_ALARM_T_S - 10):CINC_ALARM_T_S]
        lines.append(f"  HR from ECG: median {np.median(fin) if fin.size else float('nan'):.0f} bpm, "
                     f"{int((hr == 0).sum())} s at 0, {int(np.isnan(hr).sum())} s NaN; "
                     f"last 10 s before alarm: {' '.join('-' if np.isnan(v) else f'{v:.0f}' for v in last)}")
    for k in ("ecg", "ppg", "abp"):
        if picks[k] is None:
            lines.append(f"  NOTE: no {k} channel")
    return lines
