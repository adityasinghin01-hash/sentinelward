"""Signal helpers: gap-safe resampling, missing/flat statistics, 1 s grids, cuff readings, channels."""
from __future__ import annotations

import re
from fractions import Fraction
from typing import Iterable, Optional, Sequence

import numpy as np
from scipy import signal as sps

from sw_data import FS_OUT, MISSING_SENTINEL

# --------------------------------------------------------------------------- missing values


def clean_missing(x: Iterable[float]) -> np.ndarray:
    """Return a native float64 copy of ``x`` with the -32768 missing marker turned into NaN."""
    a = np.array(x, dtype=np.float64)
    a[a == MISSING_SENTINEL] = np.nan
    return a


def fill_gaps(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Linearly fill NaN stretches (edges hold the nearest value), for filtering only.

    Returns ``(filled, mask)`` where ``mask`` is True where ``x`` was missing.
    An all-missing input is filled with zeros; callers must re-apply the mask.
    """
    x = np.asarray(x, dtype=np.float64)
    mask = np.isnan(x)
    if not mask.any():
        return x.copy(), mask
    if mask.all():
        return np.zeros_like(x), mask
    idx = np.arange(x.size)
    filled = x.copy()
    filled[mask] = np.interp(idx[mask], idx[~mask], x[~mask])
    return filled, mask


def pct_missing(x: np.ndarray) -> float:
    """Percentage of NaN samples (0 for an empty array)."""
    x = np.asarray(x)
    if x.size == 0:
        return 0.0
    return float(100.0 * np.isnan(x).mean())


def flat_mask(x: np.ndarray, fs: float, seconds: float = 2.0) -> np.ndarray:
    """True for every non-NaN sample inside a run of identical values lasting at least ``seconds``."""
    x = np.asarray(x, dtype=np.float64)
    n = x.size
    if n == 0:
        return np.zeros(0, dtype=bool)
    min_len = max(2, int(round(seconds * fs)))
    same = np.empty(n, dtype=bool)
    same[0] = False
    same[1:] = x[1:] == x[:-1]
    run_id = np.cumsum(~same) - 1
    counts = np.bincount(run_id)
    return (counts[run_id] >= min_len) & ~np.isnan(x)


def pct_flat(x: np.ndarray, fs: float, seconds: float = 2.0) -> float:
    """Percentage of samples that lie in a flat run of at least ``seconds`` (2 s with no change)."""
    x = np.asarray(x)
    if x.size == 0:
        return 0.0
    return float(100.0 * flat_mask(x, fs, seconds).mean())


# --------------------------------------------------------------------------- resampling


def resample_ratio(fs_in: float) -> tuple[int, int]:
    """Return ``(up, down)`` so that ``fs_in * up / down == 125``."""
    if fs_in <= 0:
        raise ValueError(f"invalid sampling rate {fs_in}")
    frac = Fraction(FS_OUT) / Fraction(fs_in).limit_denominator(1000)
    if frac.numerator > 1000 or frac.denominator > 1000:
        raise ValueError(f"cannot resample {fs_in} Hz to {FS_OUT} Hz with a small rational ratio")
    return frac.numerator, frac.denominator


def resampled_gap_mask(mask: np.ndarray, up: int, down: int, n_out: int) -> np.ndarray:
    """Output samples whose decimation cell touches a missing input sample.

    Output ``k`` sits at input position ``k*down/up``; its cell is every input ``i`` with
    ``|i - k*down/up| < max(down/up, 1)``. For down-sampling by ``d`` that is
    ``[k*d-(d-1), k*d+(d-1)]``, so a gap grows by at most one output sample per side.
    """
    mask = np.asarray(mask, dtype=bool)
    n = mask.size
    cs = np.concatenate(([0], np.cumsum(mask, dtype=np.int64)))
    k = np.arange(n_out, dtype=np.int64)
    h = max(up, down)  # half-width in units of 1/up input samples
    lo = (k * down - h) // up + 1
    hi = -((-(k * down + h)) // up) - 1
    lo = np.clip(lo, 0, n)
    hi_excl = np.clip(hi + 1, 0, n)
    hi_excl = np.maximum(hi_excl, lo)
    return (cs[hi_excl] - cs[lo]) > 0


def resample_to_125(x: np.ndarray, fs_in: float) -> np.ndarray:
    """Resample ``x`` from ``fs_in`` to 125 Hz with resample_poly, keeping missing stretches NaN.

    Gaps are filled only to run the filter, then every output sample whose decimation cell
    touched a missing input goes back to NaN. Output length is ``ceil(len(x) * up / down)``.
    """
    x = clean_missing(x)
    up, down = resample_ratio(fs_in)
    if up == down:
        return x
    n_out = -(-x.size * up // down)
    if x.size == 0:
        return np.zeros(0)
    filled, mask = fill_gaps(x)
    if mask.all():
        return np.full(n_out, np.nan)
    y = sps.resample_poly(filled, up, down, padtype="line")[:n_out].astype(np.float64)
    if mask.any():
        y[resampled_gap_mask(mask, up, down, y.size)] = np.nan
    return y


def window_resample(x: np.ndarray, fs_in: float, start: int, n: int, margin_s: float = 1.0) -> np.ndarray:
    """Resample the window ``x[start:start+n]`` to 125 Hz using up to ``margin_s`` of context per side.

    The context feeds the filter and is cropped off, so window edges are not distorted.
    Returns exactly ``n * up / down`` samples; raises ValueError if that is not an integer
    or the window does not fit in ``x``.
    """
    x = np.asarray(x)
    up, down = resample_ratio(fs_in)
    if (n * up) % down:
        raise ValueError(f"window of {n} samples at {fs_in} Hz is not a whole number of 125 Hz samples")
    if start < 0 or start + n > x.size:
        raise ValueError(f"window [{start}, {start + n}) does not fit in {x.size} samples")
    n_out = n * up // down
    if up == down:
        return clean_missing(x[start:start + n])
    m = int(margin_s * fs_in) // down * down
    ml = min(m, start) // down * down
    mr = min(m, x.size - (start + n)) // down * down
    y = resample_to_125(x[start - ml:start + n + mr], fs_in)
    off = ml * up // down
    out = y[off:off + n_out]
    if out.size != n_out:
        raise ValueError(f"resampled window has {out.size} samples, expected {n_out}")
    return out


# --------------------------------------------------------------------------- window search


def per_minute_fractions(x: np.ndarray, fs: float) -> tuple[np.ndarray, np.ndarray]:
    """Per whole minute of ``x``: fraction missing and fraction flat (2 s rule)."""
    x = np.asarray(x, dtype=np.float64)
    per = int(round(60 * fs))
    n_min = x.size // per
    if n_min == 0:
        return np.zeros(0), np.zeros(0)
    trimmed = x[:n_min * per]
    miss = np.isnan(trimmed).reshape(n_min, per).mean(axis=1)
    flat = flat_mask(trimmed, fs).reshape(n_min, per).mean(axis=1)
    return miss, flat


def rolling_mean(v: np.ndarray, w: int) -> np.ndarray:
    """Mean of every length-``w`` window of ``v`` (length ``len(v) - w + 1``, empty if too short)."""
    v = np.asarray(v, dtype=np.float64)
    if w <= 0 or v.size < w:
        return np.zeros(0)
    cs = np.concatenate(([0.0], np.cumsum(v)))
    return (cs[w:] - cs[:-w]) / w


def first_valid_window(limits: Sequence[tuple[np.ndarray, float]], minutes: int,
                       extra_ok: Optional[np.ndarray] = None) -> Optional[int]:
    """First start minute where every per-minute fraction array stays below its limit over ``minutes``.

    ``limits`` holds ``(per_minute_fraction, max_allowed_fraction)`` pairs; arrays are cut to the
    shortest. ``extra_ok`` is an optional bool array indexed by start minute.
    """
    if not limits:
        return None
    n = min(a.size for a, _ in limits)
    if n < minutes:
        return None
    ok = np.ones(n - minutes + 1, dtype=bool)
    for arr, lim in limits:
        ok &= rolling_mean(arr[:n], minutes) < lim
    if extra_ok is not None:
        e = np.asarray(extra_ok, dtype=bool)[:ok.size]
        ok[:e.size] &= e
        ok[e.size:] = False
    hits = np.flatnonzero(ok)
    return int(hits[0]) if hits.size else None


# --------------------------------------------------------------------------- 1 s grids and cuff


def to_second_grid(times_s: np.ndarray, values: np.ndarray, duration_s: int, max_age_s: float) -> np.ndarray:
    """Put irregular samples on a 1 s grid ``t = 0 .. duration_s-1`` (seconds from window start).

    Each grid second takes the latest non-NaN sample at or before it if that sample is less
    than ``max_age_s`` old; otherwise NaN. Samples before the window may carry into it.
    """
    t = np.asarray(times_s, dtype=np.float64)
    v = clean_missing(values)
    out = np.full(int(duration_s), np.nan)
    ok = ~np.isnan(v) & ~np.isnan(t)
    t, v = t[ok], v[ok]
    if t.size == 0:
        return out
    order = np.argsort(t, kind="stable")
    t, v = t[order], v[order]
    grid = np.arange(int(duration_s), dtype=np.float64)
    j = np.searchsorted(t, grid + 1e-6, side="right") - 1
    has = j >= 0
    jj = j[has]
    age = grid[has] - t[jj]
    good = age < max_age_s - 1e-6
    idx = np.flatnonzero(has)[good]
    out[idx] = v[jj[good]]
    return out


def cuff_readings(times_s: np.ndarray, sys: np.ndarray, dia: np.ndarray, mean: np.ndarray,
                  duration_s: Optional[int] = None) -> np.ndarray:
    """Rows ``[t_offset_s, sys, dia, map]``, one per NEW cuff reading.

    A new reading is a non-NaN systolic value that differs from the previous non-NaN systolic
    value (the first non-NaN value counts). Pass samples from before the window with negative
    times so a carried-over value is not counted; only rows with ``0 <= t < duration_s`` are kept.
    """
    t = np.asarray(times_s, dtype=np.float64)
    s, d, m = clean_missing(sys), clean_missing(dia), clean_missing(mean)
    idx = np.flatnonzero(~np.isnan(s))
    if idx.size == 0:
        return np.zeros((0, 4))
    sv = s[idx]
    new = np.ones(idx.size, dtype=bool)
    new[1:] = sv[1:] != sv[:-1]
    sel = idx[new]
    rows = np.column_stack([t[sel], s[sel], d[sel], m[sel]])
    keep = rows[:, 0] >= -1e-9
    if duration_s is not None:
        keep &= rows[:, 0] < duration_s
    return rows[keep].reshape(-1, 4)


# --------------------------------------------------------------------------- reports


def stats_table(rows: Sequence[tuple[str, float, str, np.ndarray]]) -> list[str]:
    """Report lines ``signal  fs  units  missing%  flat%`` for ``(name, fs, units, data)`` rows."""
    lines = [f"  {'signal':<14}{'fs(Hz)':>8}  {'units':<8}{'missing%':>9}{'flat%':>8}"]
    for name, fs, units, data in rows:
        lines.append(f"  {name:<14}{fs:>8g}  {(units or '-'):<8}{pct_missing(data):>9.2f}{pct_flat(data, fs):>8.2f}")
    return lines


# --------------------------------------------------------------------------- channels and units

ECG_LEADS = {"II", "I", "III", "AVR", "AVL", "AVF", "V", "V1", "V2", "V3", "V4", "V5", "V6",
             "MCL", "MCL1", "ECG", "ECG_II", "ECG_V5"}


def _norm(name: str) -> str:
    return re.sub(r"[\s_\-]", "", str(name)).upper()


def pick_channel(names: Sequence[str], candidates: Sequence[str]) -> Optional[int]:
    """Index of the first candidate present in ``names`` (case-, space- and underscore-insensitive)."""
    normed = [_norm(n) for n in names]
    for cand in candidates:
        c = _norm(cand)
        if c in normed:
            return normed.index(c)
    return None


def pick_ecg(names: Sequence[str]) -> tuple[Optional[int], str]:
    """Index of lead II, else of the first ECG lead, plus a note saying which was used."""
    for i, n in enumerate(names):
        if str(n).strip() == "II":
            return i, "ECG lead II"
    for i, n in enumerate(names):
        if _norm(n) in {_norm(e) for e in ECG_LEADS} or _norm(n).startswith("ECG"):
            return i, f"ECG lead II absent; used {n} (first ECG lead)"
    return None, "no ECG lead"


def is_ecg_name(name: str) -> bool:
    """True for a channel name that is an ECG lead (see ``ECG_LEADS``) or starts with ``ECG``."""
    return _norm(name) in {_norm(e) for e in ECG_LEADS} or _norm(name).startswith("ECG")


def pick_ecg2(names: Sequence[str], first: Optional[int]) -> tuple[Optional[int], str]:
    """Second ECG lead (v1.3): lead ``V`` if present, else the next ECG lead in channel order.

    ``first`` is the index of the main lead (``pick_ecg``); the second lead is never the same
    channel. The same rule is used to train the 2-lead M2 model (``ml_v2/m2gbt/prep.py``).
    """
    if first is None:
        return None, "no main ECG lead, so no second lead"
    for i, n in enumerate(names):
        if i != first and _norm(n) == "V":
            return i, f"second ECG lead {n}"
    for i, n in enumerate(names):
        if i != first and is_ecg_name(n):
            return i, f"second ECG lead {n} (no lead V; next ECG lead)"
    return None, "no second ECG lead"


def ecg_to_mv(x: np.ndarray, units: str) -> tuple[np.ndarray, Optional[str], bool]:
    """Bring an ECG to mV from its stated units.

    Returns ``(signal, note, warn)``: ``uV`` is divided by 1000 (noted); a blank unit is kept
    with a note and ``warn=True``; any other non-mV unit is kept and noted.
    """
    u = (units or "").strip()
    if u.lower() == "mv":
        return x, None, False
    if u.lower() in {"uv", "µv", "μv"}:
        return np.asarray(x, dtype=np.float64) / 1000.0, "ECG stored in uV; divided by 1000 to mV", False
    if u == "" or u.upper() in {"NU", "?"}:
        return x, f"ECG units blank ({u!r}); values kept as stored, scale unknown", True
    return x, f"ECG units {u!r} (not mV); values kept as stored", True
