"""Per-bed build pipeline: source -> checks -> pack, plus summary.md."""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

import numpy as np

from sw_data import FS_OUT, BedError
from sw_data.beds import BedSpec, Paths, SourceData, load_beds
from sw_data.dsp import pct_missing
from sw_data.pack import SECONDS, WAVES, write_pack

MAX_REQUIRED_MISSING_PCT = 50.0
SUMMARY_HEADER = ("| bed | device | source | window | duration_s | channels | missing % | cuff | alarms | status |\n"
                  "|---|---|---|---|---|---|---|---|---|---|")


def _source_reader(dataset: str) -> Callable[[BedSpec, Paths], SourceData]:
    # Imported here so the VitalDB module is only touched for VitalDB beds.
    if dataset == "cinc2015":
        from sw_data.cinc2015 import build_source
    elif dataset == "mimic":
        from sw_data.mimic import build_source
    elif dataset == "vitaldb":
        from sw_data.vital import build_source
    else:
        raise ValueError(dataset)
    return build_source


@dataclass
class BedResult:
    """Outcome of building one bed."""

    bed_id: str
    ok: bool
    message: str
    row: str
    seconds: float = 0.0


def assemble(spec: BedSpec, sd: SourceData) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Check a SourceData against the bed's requirements and lay out the pack arrays and json."""
    dur = int(sd.duration_s)
    arrays: dict[str, np.ndarray] = {}
    for k in WAVES:
        if k not in sd.waves:
            continue
        a = np.asarray(sd.waves[k], dtype=np.float64)
        if a.shape != (dur * FS_OUT,):
            raise BedError(spec.bed_id, f"{k} has {a.size} samples, expected {dur * FS_OUT}")
        arrays[k] = a
    for k in WAVES:
        if spec.wants(k):
            if k not in arrays:
                raise BedError(spec.bed_id, f"lacks required signal {k}")
            p = pct_missing(arrays[k])
            if p > MAX_REQUIRED_MISSING_PCT:
                name = sd.source.get("channels", {}).get(k, {}).get("name", k)
                raise BedError(spec.bed_id, f"required signal {k} ({name}) is {p:.1f} % missing in the window "
                                            f"(> {MAX_REQUIRED_MISSING_PCT:.0f} %); pick a different window")
    for k in SECONDS:
        v = getattr(sd, k)
        a = np.full(dur, np.nan) if v is None else np.asarray(v, dtype=np.float64)
        if a.shape != (dur,):
            raise BedError(spec.bed_id, f"{k} has {a.size} values, expected {dur}")
        arrays[k] = a
    if spec.wants("numerics") or spec.wants("numbers"):
        p = pct_missing(arrays["hr"])
        if p > MAX_REQUIRED_MISSING_PCT:
            raise BedError(spec.bed_id, f"required numeric HR is {p:.1f} % missing in the window "
                                        f"(> {MAX_REQUIRED_MISSING_PCT:.0f} %); pick a different window")
    nibp = np.asarray(sd.nibp, dtype=np.float64).reshape(-1, 4)
    arrays["nibp"] = nibp
    meta = {
        "bed_id": spec.bed_id,
        "device_id": spec.device_id,
        "source": sd.source,
        "duration_s": dur,
        "alarms": sd.alarms,
        "notes": sd.notes,
        "required_signals": spec.signals,
    }
    return arrays, meta


def build_bed(spec: BedSpec, paths: Paths) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Read and check one bed entirely in memory; raises BedError (with the bed ID) on any problem."""
    try:
        sd = _source_reader(spec.dataset)(spec, paths)
        return assemble(spec, sd)
    except BedError:
        raise
    except Exception as exc:
        raise BedError(spec.bed_id, f"{type(exc).__name__}: {exc}") from exc


def _source_label(meta: dict[str, Any]) -> tuple[str, str]:
    s = meta["source"]
    if "record" in s:
        return f"2015 {s['record']}", "whole record"
    if "piece" in s:
        return f"MIMIC {s['patient']}/{s['piece']}", f"piece +{s['window_start_s']:.0f} s"
    return f"VitalDB {s.get('case')}", f"minute {s.get('window_start_min', 0):.1f}"


def summary_row(meta: dict[str, Any], arrays: dict[str, np.ndarray]) -> str:
    """One summary.md table row for a built bed."""
    src, win = _source_label(meta)
    chans = " ".join(k for k in WAVES + SECONDS if k in arrays)
    miss = " ".join(f"{k} {pct_missing(arrays[k]):.1f}" for k in WAVES + SECONDS if k in arrays)
    alarms = ", ".join(f"{a['code']}@{a['t_offset_s']}s {'T' if a['true_alarm'] else 'F'}"
                       for a in meta["alarms"]) or "-"
    return (f"| {meta['bed_id']} | {meta['device_id']} | {src} | {win} | {meta['duration_s']} | {chans} | "
            f"{miss} | {arrays['nibp'].shape[0]} | {alarms} | OK |")


def fail_row(spec: BedSpec, reason: str) -> str:
    """summary.md row for a bed that failed."""
    ident = spec.record or spec.piece or spec.case or "-"
    reason = reason.replace("|", "/")
    return f"| {spec.bed_id} | {spec.device_id} | {spec.dataset} {ident} | - | - | - | - | - | - | FAIL: {reason} |"


def write_summary(out: Path, rows: dict[str, str]) -> Path:
    """Merge ``rows`` (bed ID -> row) into ``out/summary.md``, keeping rows of beds not rebuilt."""
    path = out / "summary.md"
    merged: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            cells = [c.strip() for c in line.split("|")]
            if len(cells) > 2 and cells[1].startswith("B") and cells[1][1:].isdigit():
                merged[cells[1]] = line
    merged.update(rows)
    body = "\n".join(merged[b] for b in sorted(merged))
    path.write_text(f"# SentinelWard bed packs\n\n{SUMMARY_HEADER}\n{body}\n", encoding="utf-8")
    return path


def build(beds_yaml: str | Path, out_dir: str | Path, only: Optional[Iterable[str]] = None,
          log: Callable[[str], None] = print) -> list[BedResult]:
    """Build every bed (or those in ``only``) from beds.yaml into ``out_dir``; returns one result per bed."""
    paths, specs = load_beds(beds_yaml)
    wanted = None if only is None else {b.strip() for b in only if b.strip()}
    if wanted:
        unknown = wanted - {s.bed_id for s in specs}
        if unknown:
            raise ValueError(f"unknown bed(s) {sorted(unknown)} in --beds")
        specs = [s for s in specs if s.bed_id in wanted]
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    results: list[BedResult] = []
    for spec in specs:
        t0 = time.perf_counter()
        try:
            arrays, meta = build_bed(spec, paths)
            write_pack(out, spec.bed_id, arrays, meta)
            row = summary_row(meta, arrays)
            res = BedResult(spec.bed_id, True, f"{arrays['hr'].size} s, {', '.join(k for k in arrays)}", row)
        except BedError as exc:
            res = BedResult(spec.bed_id, False, str(exc), fail_row(spec, exc.reason))
            if (out / f"{spec.bed_id}.npz").exists() or (out / f"{spec.bed_id}.json").exists():
                res.message += f" (an older {spec.bed_id} pack is still in {out})"
        res.seconds = time.perf_counter() - t0
        log(f"{'OK  ' if res.ok else 'FAIL'} {res.message if not res.ok else spec.bed_id + ': ' + res.message}"
            f"  [{res.seconds:.1f} s]")
        results.append(res)
    summary = write_summary(out, {r.bed_id: r.row for r in results})
    log(f"summary: {summary}")
    return results
