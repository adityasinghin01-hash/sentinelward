"""MIMIC-III Waveform Database Matched Subset: 125 Hz pieces, multi-segment masters, 1 Hz numerics."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Optional

import numpy as np
import wfdb

from sw_data import BedError
from sw_data.beds import BedSpec, Paths, SourceData
from sw_data.dsp import (clean_missing, cuff_readings, ecg_to_mv, first_valid_window, pick_channel,
                         pick_ecg, pick_ecg2, per_minute_fractions, stats_table, to_second_grid, window_resample)

DATASET_LABEL = "MIMIC-III WDB matched subset"
PIECE_RE = re.compile(r"^\d+_\d{4}$")
MASTER_RE = re.compile(r"^p\d{6}-\d{4}-\d{2}-\d{2}-\d{2}-\d{2}$")
PATIENT_RE = re.compile(r"^p\d{6}$")
GROUP_RE = re.compile(r"^p\d{2}$")

NUMERIC_CHANNELS = {
    "hr": ["HR"],
    "spo2": ["SpO2", "%SpO2"],
    "rr": ["RESP", "RR"],
    "nbp_sys": ["NBP Sys", "NBP SYS", "NBPs"],
    "nbp_dia": ["NBP Dias", "NBP Dia", "NBPd"],
    "nbp_mean": ["NBP Mean", "NBPm"],
}
CUFF_LOOKBACK_S = 3600.0


# --------------------------------------------------------------------------- layout


def hea(stem: Path) -> Path:
    """The .hea file of a record stem."""
    return stem.with_name(stem.name + ".hea")


def iter_patients(root: str | Path) -> list[Path]:
    """Patient folders under a sample root, in folder order (``p00/p000052`` or ``p000052``)."""
    root = Path(root)
    out: list[Path] = []
    if PATIENT_RE.match(root.name) and root.is_dir():
        return [root]
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        if PATIENT_RE.match(d.name):
            out.append(d)
        elif GROUP_RE.match(d.name):
            out.extend(sorted(x for x in d.iterdir() if x.is_dir() and PATIENT_RE.match(x.name)))
    return out


def patient_dir(root: Path, patient: str) -> Path:
    """Folder of ``patient`` under the sample root; raises FileNotFoundError."""
    for cand in (root / patient[:3] / patient, root / patient):
        if cand.is_dir():
            return cand
    hits = sorted(root.glob(f"*/{patient}"))
    if hits:
        return hits[0]
    raise FileNotFoundError(f"MIMIC patient folder {patient} not found under {root}")


def master_stems(pdir: Path) -> list[Path]:
    """Master (multi-segment) record stems of a patient folder, sorted."""
    return sorted(p.with_suffix("") for p in pdir.glob("*.hea") if MASTER_RE.match(p.stem))


def _header_lines(path: Path) -> list[str]:
    with open(path) as f:
        return [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]


def numerics_stem(master: Path) -> Path:
    """Numerics record stem for a master record (``<master>n``).

    Some MIMIC numerics headers carry a start time a few seconds later than their master, so
    their name differs (e.g. master ``p000107-2122-05-14-21-01`` and numerics
    ``p000107-2122-05-14-21-02n``). When ``<master>n`` is absent, the one numerics header in the
    folder whose signal file is ``<record id>n.dat`` (the record id of the master's segments) is
    used instead; the start-time difference is then applied by ``start_delta_s``.
    """
    default = master.with_name(master.name + "n")
    if hea(default).is_file() or not hea(master).is_file():
        return default
    try:
        lines = _header_lines(hea(master))
        seg = next((ln.split()[0] for ln in lines[1:] if ln.split()[0] != "~"), None)
    except OSError:
        return default
    if not seg or "_" not in seg:
        return default
    want = seg.split("_")[0] + "n.dat"
    hits = []
    for h in sorted(master.parent.glob("p*n.hea")):
        try:
            sig = _header_lines(h)[1:2]
        except OSError:
            continue
        if sig and sig[0].split()[0] == want:
            hits.append(h.with_suffix(""))
    return hits[0] if len(hits) == 1 else default


@dataclass
class PieceLoc:
    """Where a piece sits inside its master record."""

    master: Path
    piece: str
    offset_samples: int
    length: int
    fs: float
    master_header: Any

    @property
    def offset_s(self) -> float:
        return self.offset_samples / self.fs


def piece_offset(seg_names: list[str], seg_lens: list[int], piece: str) -> int:
    """Samples before ``piece`` in a master record: the sum of all earlier segment lengths."""
    i = list(seg_names).index(piece)
    return int(sum(int(n) for n in seg_lens[:i]))


def locate_piece(pdir: Path, piece: str) -> PieceLoc:
    """Find the master record listing ``piece``; raises LookupError if none does."""
    for m in master_stems(pdir):
        h = wfdb.rdheader(str(m))
        names = list(getattr(h, "seg_name", None) or [])
        if piece in names:
            i = names.index(piece)
            return PieceLoc(master=m, piece=piece, offset_samples=piece_offset(names, h.seg_len, piece),
                            length=int(h.seg_len[i]), fs=float(h.fs), master_header=h)
    raise LookupError(f"piece {piece} is not listed in any master header in {pdir}")


def _header_start(h: Any) -> tuple[Optional[date], Optional[time]]:
    return getattr(h, "base_date", None), getattr(h, "base_time", None)


def start_delta_s(master_hdr: Any, num_hdr: Any) -> tuple[float, Optional[str]]:
    """Seconds by which the numerics record starts after its master (0 when not both stated)."""
    md, mt = _header_start(master_hdr)
    nd, nt = _header_start(num_hdr)
    if mt is None or nt is None:
        return 0.0, None
    if md is not None and nd is not None:
        delta = (datetime.combine(nd, nt) - datetime.combine(md, mt)).total_seconds()
    else:
        delta = (datetime.combine(date(2000, 1, 1), nt) - datetime.combine(date(2000, 1, 1), mt)).total_seconds()
        delta = (delta + 43200) % 86400 - 43200
    if abs(delta) < 1e-6:
        return 0.0, None
    return delta, f"numerics start {delta:+.3f} s from the master record start (applied)"


# --------------------------------------------------------------------------- numerics


def read_numerics(num: Path, delta_s: float, t0_master_s: float, duration_s: float,
                  lookback_s: float = 0.0) -> dict[str, Any]:
    """Numerics samples around a window of the master record.

    Returns ``{"fs", "names", "length_s", "times", "series": {key: values}}`` where ``times``
    are seconds from the window start (negative = before it) and ``series`` holds HR, SpO2,
    RR and NBP channels that exist.
    """
    h = wfdb.rdheader(str(num))
    fs_n = float(h.fs)
    names = [str(n) for n in h.sig_name]
    length = int(h.sig_len or 0)
    out: dict[str, Any] = {"fs": fs_n, "names": names, "length_s": length / fs_n,
                           "start_delta_s": delta_s, "times": np.zeros(0), "series": {}}
    idx = {k: pick_channel(names, c) for k, c in NUMERIC_CHANNELS.items()}
    chans = sorted({i for i in idx.values() if i is not None})
    i0 = max(0, int(math.floor((t0_master_s - lookback_s - delta_s) * fs_n)))
    i1 = min(length, int(math.ceil((t0_master_s + duration_s - delta_s) * fs_n)) + 1)
    if not chans or i1 <= i0:
        return out
    rec = wfdb.rdrecord(str(num), sampfrom=i0, sampto=i1, channels=chans)
    col = {ch: j for j, ch in enumerate(chans)}
    out["times"] = delta_s + (i0 + np.arange(i1 - i0)) / fs_n - t0_master_s
    out["series"] = {k: clean_missing(rec.p_signal[:, col[i]]) for k, i in idx.items() if i is not None}
    return out


def numerics_on_grid(nd: dict[str, Any], duration_s: int) -> dict[str, np.ndarray]:
    """HR / SpO2 / RR on the 1 s grid (NaN where missing) and the NBP readings."""
    max_age = max(1.0, 1.0 / nd["fs"]) if nd["fs"] > 0 else 1.0
    t = nd["times"]
    s = nd["series"]
    out = {k: (to_second_grid(t, s[k], duration_s, max_age) if k in s else np.full(duration_s, np.nan))
           for k in ("hr", "spo2", "rr")}
    if "nbp_sys" in s:
        nan = np.full(t.size, np.nan)
        out["nibp"] = cuff_readings(t, s["nbp_sys"], s.get("nbp_dia", nan), s.get("nbp_mean", nan), duration_s)
    else:
        out["nibp"] = np.zeros((0, 4))
    return out


# --------------------------------------------------------------------------- build


def _wave_picks(names: list[str], want_resp: bool) -> tuple[dict[str, Optional[int]], str]:
    ecg_idx, ecg_note = pick_ecg(names)
    picks = {"ecg": ecg_idx, "ecg2": pick_ecg2(names, ecg_idx)[0],   # v1.3: optional second ECG lead
             "ppg": pick_channel(names, ["PLETH"]), "abp": pick_channel(names, ["ABP", "ART"])}
    if want_resp:
        picks["resp"] = pick_channel(names, ["RESP"])
    return picks, ecg_note


def build_source(spec: BedSpec, paths: Paths) -> SourceData:
    """Read a MIMIC piece window plus its lined-up numerics into pack grids."""
    spec.require("patient", "piece", "start_s")
    if spec.duration_s is None:
        raise BedError(spec.bed_id, "duration_s not set")
    if paths.mimic is None:
        raise BedError(spec.bed_id, "paths.mimic is not set in beds.yaml")
    try:
        pdir = patient_dir(paths.mimic, spec.patient)
    except FileNotFoundError as exc:
        raise BedError(spec.bed_id, str(exc)) from exc
    piece_stem = pdir / spec.piece
    if not hea(piece_stem).is_file():
        raise BedError(spec.bed_id, f"MIMIC piece not found: {hea(piece_stem)}")
    try:
        loc = locate_piece(pdir, spec.piece)
    except LookupError as exc:
        raise BedError(spec.bed_id, str(exc)) from exc

    ph = wfdb.rdheader(str(piece_stem))
    fs = float(ph.fs)
    names = [str(n) for n in ph.sig_name]
    units = [str(u) for u in ph.units]
    length = int(ph.sig_len)
    dur = int(spec.duration_s)
    start = float(spec.start_s)
    n0 = int(round(start * fs))
    n = int(round(dur * fs))
    if n0 + n > length:
        raise BedError(spec.bed_id, f"piece {spec.piece} is {length / fs:.0f} s long; "
                                    f"window {start:.0f}+{dur} s does not fit")
    picks, ecg_note = _wave_picks(names, spec.wants("resp"))
    lacking = [k for k in ("ecg", "ppg", "abp", "resp") if spec.wants(k) and picks.get(k) is None]
    if lacking:
        raise BedError(spec.bed_id, f"piece {spec.piece} lacks required signal(s) {lacking}; it has {names}")

    present = {k: i for k, i in picks.items() if i is not None}
    margin = 0 if abs(fs - 125.0) < 1e-9 else int(fs)
    a, b = max(0, n0 - margin), min(length, n0 + n + margin)
    chans = sorted(set(present.values()))
    rec = wfdb.rdrecord(str(piece_stem), sampfrom=a, sampto=b, channels=chans)
    col = {ch: j for j, ch in enumerate(chans)}
    notes: list[str] = []
    waves: dict[str, np.ndarray] = {}
    channels: dict[str, dict[str, Any]] = {}
    for key, idx in present.items():
        x = clean_missing(rec.p_signal[:, col[idx]])
        unit = units[idx]
        if key in ("ecg", "ecg2"):
            notes.append(ecg_note if key == "ecg" else pick_ecg2(names, picks["ecg"])[1])
            x, note, _warn = ecg_to_mv(x, unit)
            if note:
                notes.append(note)
                if unit.strip().lower() in {"uv", "µv", "μv"}:
                    unit = "mV"
        if key == "ecg2" and not np.isfinite(x[n0 - a:n0 - a + n]).any():
            notes.append(f"second ECG lead {names[idx]} is empty in the window; ecg2 left out")
            continue
        try:
            waves[key] = window_resample(x, fs, n0 - a, n)
        except ValueError as exc:
            raise BedError(spec.bed_id, f"{key}: {exc}") from exc
        channels[key] = {"name": names[idx], "fs": fs, "units": unit}

    t0 = loc.offset_s + start
    num = numerics_stem(loc.master)
    numerics_found = False
    grid = {"hr": np.full(dur, np.nan), "spo2": np.full(dur, np.nan), "rr": np.full(dur, np.nan),
            "nibp": np.zeros((0, 4))}
    num_info: dict[str, Any] = {"numerics_record": None}
    if hea(num).is_file():
        nh = wfdb.rdheader(str(num))
        delta, dnote = start_delta_s(loc.master_header, nh)
        if dnote:
            notes.append(dnote)
        nd = read_numerics(num, delta, t0, dur, lookback_s=CUFF_LOOKBACK_S)
        if nd["times"].size:
            grid = numerics_on_grid(nd, dur)
            numerics_found = True
        else:
            notes.append("numerics record does not cover this window")
        num_info = {"numerics_record": num.name, "numerics_fs": nd["fs"], "numerics_channels": nd["names"],
                    "numerics_start_delta_s": delta}
        for k in ("hr", "spo2", "rr"):
            if k not in nd["series"]:
                notes.append(f"numerics have no {k.upper()} channel; {k} is NaN")
        if "nbp_sys" not in nd["series"]:
            notes.append("numerics have no NBP; nibp is empty")
    else:
        notes.append(f"no numerics record {num.name}; hr/spo2/rr NaN, nibp empty")
    if spec.wants("numerics") and not numerics_found:
        raise BedError(spec.bed_id, f"required numerics missing for piece {spec.piece} "
                                    f"(record {num.name} absent or not covering the window)")
    notes.append(f"numerics lined up: piece offset {loc.offset_s:.3f} s in {loc.master.name}")

    source = {
        "dataset": DATASET_LABEL,
        "patient": spec.patient,
        "piece": spec.piece,
        "master_record": loc.master.name,
        "master_offset_s": loc.offset_s,
        "window_start_s": start,
        "window_start_master_s": t0,
        "piece_length_s": length / fs,
        "channels": channels,
        "original_channels": [{"name": nm, "fs": fs, "units": u} for nm, u in zip(names, units)],
        **num_info,
    }
    return SourceData(dataset="mimic", duration_s=dur, source=source, waves=waves,
                      hr=grid["hr"], spo2=grid["spo2"], rr=grid["rr"], nibp=grid["nibp"],
                      alarms=[], notes=notes, numerics_found=numerics_found)


# --------------------------------------------------------------------------- check


def alignment_lines(loc: PieceLoc) -> list[str]:
    """Report how the numerics record lines up with a piece."""
    num = numerics_stem(loc.master)
    lines = [f"  master {loc.master.name}: piece offset {loc.offset_samples} samples = {loc.offset_s:.3f} s"]
    if not hea(num).is_file():
        return lines + [f"  numerics line up: NO (no numerics record {num.name})"]
    nh = wfdb.rdheader(str(num))
    delta, dnote = start_delta_s(loc.master_header, nh)
    span = loc.length / loc.fs
    nd = read_numerics(num, delta, loc.offset_s, span)
    num_end = delta + nd["length_s"]
    covered = max(0.0, min(loc.offset_s + span, num_end) - max(loc.offset_s, delta))
    cov_pct = 100.0 * covered / span if span > 0 else 0.0
    hr = nd["series"].get("hr")
    hr_valid = 100.0 * np.isfinite(hr).mean() if hr is not None and hr.size else 0.0
    lines.append(f"  numerics {num.name}: {nd['fs']:g} Hz, {nd['length_s']:.0f} s, channels {', '.join(nd['names'])}")
    if dnote:
        lines.append(f"  {dnote}")
    ok = cov_pct >= 99.0 and hr_valid > 50.0
    lines.append(f"  numerics line up: {'YES' if ok else 'NO'} (cover {cov_pct:.1f} % of the piece, "
                 f"HR valid {hr_valid:.1f} % over the piece)")
    return lines


def check_piece(stem: Path) -> list[str]:
    """One-screen check report for one MIMIC piece."""
    ph = wfdb.rdheader(str(stem))
    fs = float(ph.fs)
    names = [str(n) for n in ph.sig_name]
    lines = [f"== {stem.name}  [{DATASET_LABEL}]  {stem}",
             f"  length {ph.sig_len / fs:.1f} s = {ph.sig_len / fs / 60:.1f} min ({ph.sig_len} samples at {fs:g} Hz)"]
    rec = wfdb.rdrecord(str(stem))
    lines += stats_table([(nm, fs, u, clean_missing(rec.p_signal[:, i]))
                          for i, (nm, u) in enumerate(zip(names, ph.units))])
    picks, ecg_note = _wave_picks(names, True)
    lines.append("  pack: " + "  ".join(f"{k}={names[i] if i is not None else '-'}" for k, i in picks.items())
                 + f"   ({ecg_note})")
    if picks["ecg"] is not None:
        _, note, warn = ecg_to_mv(np.zeros(1), ph.units[picks["ecg"]])
        if note:
            lines.append(f"  {'WARNING' if warn else 'NOTE'}: {note}")
    try:
        lines += alignment_lines(locate_piece(stem.parent, stem.name))
    except LookupError as exc:
        lines.append(f"  numerics line up: NO ({exc})")
    return lines


def check_master(stem: Path) -> list[str]:
    """Compact check report for a master record: its pieces, lengths, offsets and signals."""
    h = wfdb.rdheader(str(stem))
    fs = float(h.fs)
    num = numerics_stem(stem)
    lines = [f"== {stem.name}  [{DATASET_LABEL} master]  {stem}",
             f"  {len(h.seg_name)} segments, {h.sig_len / fs / 3600:.2f} h at {fs:g} Hz; "
             f"numerics {'present' if hea(num).is_file() else 'ABSENT'} ({num.name})",
             f"  {'piece':<16}{'offset_s':>10}{'length':>10}  signals"]
    off = 0
    for name, ln in zip(h.seg_name, h.seg_len):
        ln = int(ln)
        if name == "~":
            label = "(gap)"
        elif name.endswith("_layout"):
            label = "(layout)"
        elif hea(stem.parent / name).is_file():
            label = ", ".join(str(s) for s in wfdb.rdheader(str(stem.parent / name)).sig_name)
        else:
            label = "(header missing)"
        if ln > 0 or name.endswith("_layout"):
            lines.append(f"  {name:<16}{off / fs:>10.0f}{ln / fs / 60:>8.1f}min  {label}")
        off += ln
    return lines


# --------------------------------------------------------------------------- pick-mimic


def _suggest_start(pdir: Path, loc: PieceLoc, ii: int, pl: int, minutes: int) -> Optional[int]:
    """First start (s) of a ``minutes`` window with II and PLETH <5 % missing/flat and HR <=50 % missing."""
    stem = pdir / loc.piece
    fs = loc.fs
    per_min = int(round(60 * fs))
    total_min = loc.length // per_min
    if total_min < minutes:
        return None
    hr_miss = np.ones(total_min)
    num = numerics_stem(loc.master)
    if hea(num).is_file():
        delta, _ = start_delta_s(loc.master_header, wfdb.rdheader(str(num)))
        nd = read_numerics(num, delta, loc.offset_s, total_min * 60)
        if "hr" in nd["series"]:
            hr = numerics_on_grid(nd, total_min * 60)["hr"]
            hr_miss = np.isnan(hr).reshape(total_min, 60).mean(axis=1)
    acc = {k: [] for k in ("mi", "fi", "mp", "fp")}
    chunk_min = 60
    for m0 in range(0, total_min, chunk_min):
        m1 = min(total_min, m0 + chunk_min)
        rec = wfdb.rdrecord(str(stem), sampfrom=m0 * per_min, sampto=m1 * per_min, channels=sorted({ii, pl}))
        col = {ch: j for j, ch in enumerate(sorted({ii, pl}))}
        mi, fi = per_minute_fractions(clean_missing(rec.p_signal[:, col[ii]]), fs)
        mp, fp = per_minute_fractions(clean_missing(rec.p_signal[:, col[pl]]), fs)
        for k, v in (("mi", mi), ("fi", fi), ("mp", mp), ("fp", fp)):
            acc[k].append(v)
        arrs = {k: np.concatenate(v) for k, v in acc.items()}
        w = first_valid_window([(arrs["mi"], 0.05), (arrs["fi"], 0.05), (arrs["mp"], 0.05), (arrs["fp"], 0.05),
                                (hr_miss[:arrs["mi"].size], 0.5 + 1e-9)], minutes)
        if w is not None:
            return w * 60
    return None


def pick_mimic(root: str | Path, exclude: list[str], need: int, minutes: int = 22,
               min_hours: float = 1.0) -> list[dict[str, Any]]:
    """Next patients (folder order) with a piece >= ``min_hours`` holding II and PLETH, plus numerics.

    One row per patient: patient, master, piece, piece length (s) and a suggested start (s).
    """
    found: list[dict[str, Any]] = []
    excluded = {e.strip() for e in exclude if e.strip()}
    for pdir in iter_patients(root):
        if len(found) >= need:
            break
        if pdir.name in excluded:
            continue
        row = _first_good_piece(pdir, minutes, min_hours)
        if row is not None:
            found.append(row)
    return found


def _first_good_piece(pdir: Path, minutes: int, min_hours: float) -> Optional[dict[str, Any]]:
    for m in master_stems(pdir):
        if not hea(numerics_stem(m)).is_file():
            continue
        h = wfdb.rdheader(str(m))
        fs = float(h.fs)
        names = list(h.seg_name or [])
        for i, (seg, ln) in enumerate(zip(names, h.seg_len)):
            ln = int(ln)
            if seg == "~" or seg.endswith("_layout") or ln < min_hours * 3600 * fs:
                continue
            if not hea(pdir / seg).is_file():
                continue
            sig = [str(s) for s in wfdb.rdheader(str(pdir / seg)).sig_name]
            ii = pick_channel(sig, ["II"])
            pl = pick_channel(sig, ["PLETH"])
            if ii is None or pl is None:
                continue
            loc = PieceLoc(master=m, piece=seg, offset_samples=piece_offset(names, h.seg_len, seg),
                           length=ln, fs=fs, master_header=h)
            start = _suggest_start(pdir, loc, ii, pl, minutes)
            if start is None:
                continue
            return {"patient": pdir.name, "master": m.name, "piece": seg, "length_s": ln / fs,
                    "start_s": start, "signals": sig}
    return None
