"""Bed pack I/O: explicit little-endian float32 arrays, sha256, atomic writes, and verification."""
from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np

from sw_data import FS_OUT, LOADER_VERSION, PACK_DTYPE
from sw_data.dsp import pct_missing

WAVES = ("ecg", "ppg", "abp", "resp")
SECONDS = ("hr", "spo2", "rr")
ALL_ARRAYS = WAVES + SECONDS + ("nibp",)
MISSING_TOL_PCT = 0.01


def to_le32(x: Any) -> np.ndarray:
    """C-contiguous copy of ``x`` as explicit little-endian float32 (``'<f4'``); NaN is kept."""
    return np.ascontiguousarray(np.asarray(x, dtype=np.float64).astype(PACK_DTYPE))


def sha256_array(a: np.ndarray) -> str:
    """sha256 of the array's ``'<f4'`` bytes in C order."""
    return hashlib.sha256(np.ascontiguousarray(np.asarray(a).astype(PACK_DTYPE, copy=False)).tobytes()).hexdigest()


def expected_shape(name: str, duration_s: int, nibp_rows: int) -> tuple[int, ...]:
    """Shape an array must have in a pack of ``duration_s`` seconds."""
    if name in WAVES:
        return (duration_s * FS_OUT,)
    if name in SECONDS:
        return (duration_s,)
    if name == "nibp":
        return (nibp_rows, 4)
    raise KeyError(name)


def _jsonable(v: Any) -> Any:
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, Path):
        return str(v)
    return v


def missing_pcts(arrays: dict[str, np.ndarray]) -> dict[str, float]:
    """Missing-value % per waveform and per-second channel (nibp is a list of readings, not a grid)."""
    return {k: round(pct_missing(a), 4) for k, a in arrays.items() if k != "nibp"}


def finish_meta(meta: dict[str, Any], arrays: dict[str, np.ndarray]) -> dict[str, Any]:
    """Add channels, shapes, byte-order labels, missing %, sha256, version and time to ``meta``."""
    meta = dict(meta)
    meta["fs"] = FS_OUT
    meta["channels"] = [k for k in ALL_ARRAYS if k in arrays]
    meta["byte_order"] = "little"
    meta["dtype"] = PACK_DTYPE
    meta["shapes"] = {k: list(a.shape) for k, a in arrays.items()}
    meta["missing_pct"] = missing_pcts(arrays)
    meta["nibp_readings"] = int(arrays["nibp"].shape[0]) if "nibp" in arrays else 0
    meta["sha256"] = {k: sha256_array(a) for k, a in arrays.items()}
    meta["loader_version"] = LOADER_VERSION
    meta["created_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return _jsonable(meta)


def write_pack(out_dir: str | Path, bed_id: str, arrays: dict[str, np.ndarray],
               meta: dict[str, Any]) -> tuple[Path, Path]:
    """Write ``<bed_id>.npz`` and ``<bed_id>.json`` via temporary files and atomic renames."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    arrays = {k: to_le32(v) for k, v in arrays.items()}
    meta = finish_meta(meta, arrays)
    npz, js = out / f"{bed_id}.npz", out / f"{bed_id}.json"
    tmp_npz, tmp_js = out / f".{bed_id}.npz.tmp", out / f".{bed_id}.json.tmp"
    try:
        with open(tmp_npz, "wb") as fh:
            np.savez(fh, **arrays)
        with open(tmp_js, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2, allow_nan=False)
            fh.write("\n")
        os.replace(tmp_npz, npz)
        os.replace(tmp_js, js)
    finally:
        for t in (tmp_npz, tmp_js):
            if t.exists():
                t.unlink()
    return npz, js


def load_pack(out_dir: str | Path, bed_id: str) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Load a pack's arrays (as stored, ``'<f4'``) and its json."""
    out = Path(out_dir)
    with open(out / f"{bed_id}.json", encoding="utf-8") as fh:
        meta = json.load(fh)
    with np.load(out / f"{bed_id}.npz", allow_pickle=False) as z:
        arrays = {k: z[k] for k in z.files}
    return arrays, meta


def verify_pack(out_dir: str | Path, bed_id: str) -> list[str]:
    """Problems found in one pack (an empty list means PASS)."""
    problems: list[str] = []
    try:
        arrays, meta = load_pack(out_dir, bed_id)
    except Exception as exc:  # corrupt zip, bad CRC, bad json ...
        return [f"cannot load: {type(exc).__name__}: {exc}"]
    if meta.get("bed_id") != bed_id:
        problems.append(f"json bed_id {meta.get('bed_id')!r} != file name")
    if meta.get("fs") != FS_OUT:
        problems.append(f"fs {meta.get('fs')} != {FS_OUT}")
    if meta.get("byte_order") != "little" or meta.get("dtype") != PACK_DTYPE:
        problems.append(f"byte-order labels {meta.get('byte_order')!r}/{meta.get('dtype')!r} != 'little'/'{PACK_DTYPE}'")
    dur = meta.get("duration_s")
    if not isinstance(dur, int) or dur <= 0:
        return problems + [f"bad duration_s {dur!r}"]
    sha = meta.get("sha256") or {}
    listed = set(meta.get("channels") or [])
    if set(arrays) != set(sha) or set(arrays) != listed:
        problems.append(f"arrays {sorted(arrays)} vs json sha256 {sorted(sha)} / channels {sorted(listed)}")
    for k in SECONDS + ("nibp",):
        if k not in arrays:
            problems.append(f"{k} array missing")
    nibp_rows = int(arrays["nibp"].shape[0]) if "nibp" in arrays and arrays["nibp"].ndim == 2 else -1
    for k, a in arrays.items():
        if k not in ALL_ARRAYS:
            problems.append(f"unexpected array {k}")
            continue
        if a.dtype.str != PACK_DTYPE:
            problems.append(f"{k} dtype {a.dtype.str} != {PACK_DTYPE}")
        want = expected_shape(k, dur, nibp_rows)
        if tuple(a.shape) != want:
            problems.append(f"{k} shape {tuple(a.shape)} != {want}")
        if sha.get(k) != sha256_array(a):
            problems.append(f"{k} sha256 mismatch")
    if nibp_rows != meta.get("nibp_readings"):
        problems.append(f"nibp rows {nibp_rows} != nibp_readings {meta.get('nibp_readings')}")
    stored = meta.get("missing_pct") or {}
    for k, p in missing_pcts(arrays).items():
        s: Optional[float] = stored.get(k)
        if s is None or abs(float(s) - p) > MISSING_TOL_PCT:
            problems.append(f"{k} missing {p:.4f} % != json {s}")
    return problems


def verify_folder(out_dir: str | Path) -> list[tuple[str, list[str]]]:
    """``(bed_id, problems)`` for every pack (json or npz) in ``out_dir``, sorted by bed ID."""
    out = Path(out_dir)
    ids = sorted({p.stem for p in out.glob("B*.json")} | {p.stem for p in out.glob("B*.npz")})
    return [(b, verify_pack(out, b)) for b in ids]
