"""Heart rate from the ECG for records without numerics (PhysioNet/CinC 2015)."""
from __future__ import annotations

import math

import numpy as np
from scipy import signal as sps

from sw_data.dsp import fill_gaps

BAND_HZ = (5.0, 15.0)
REFRACTORY_S = 0.25
BLOCK_S = 8.0
REL_BLOCK = 0.35
REL_GLOBAL = 0.15
FLOOR_MV = 0.1
WINDOW_S = 5


def detect_beats(ecg: np.ndarray, fs: float) -> np.ndarray:
    """Sample indices of QRS peaks in ``ecg`` (mV, NaN = missing).

    The ECG is band-passed 5-15 Hz (zero phase); peaks of the rectified signal at least 0.25 s
    apart are kept if they exceed max(0.35 x 8 s block 98th percentile, 0.15 x record 98th
    percentile, 0.1 mV). The fixed floor keeps a flatline's noise from counting as beats.
    """
    x = np.asarray(ecg, dtype=np.float64)
    filled, mask = fill_gaps(x)
    if x.size < int(fs) or mask.all():
        return np.zeros(0, dtype=np.int64)
    sos = sps.butter(2, BAND_HZ, btype="bandpass", fs=fs, output="sos")
    y = np.abs(sps.sosfiltfilt(sos, filled))
    y[mask] = 0.0
    g = float(np.percentile(y[~mask], 98))
    block = max(1, int(BLOCK_S * fs))
    thr = np.empty_like(y)
    for b0 in range(0, y.size, block):
        seg = y[b0:b0 + block]
        segv = seg[~mask[b0:b0 + block]]
        bp = float(np.percentile(segv, 98)) if segv.size else 0.0
        thr[b0:b0 + block] = max(REL_BLOCK * bp, REL_GLOBAL * g, FLOOR_MV)
    peaks, _ = sps.find_peaks(y, height=thr, distance=max(1, int(round(REFRACTORY_S * fs))))
    return peaks.astype(np.int64)


def hr_from_ecg(ecg: np.ndarray, fs: float, duration_s: int) -> np.ndarray:
    """1 Hz heart rate (integer beats/min as float, NaN = unknown) from an ECG.

    ``hr[t]`` = round(60 / median beat gap) over the 5 s ending at the end of second ``t``.
    Fewer than 2 beats in a full 5 s window with the ECG at least 50 % valid gives 0 (flatline).
    A window more than 50 % missing, or a missing ECG, gives NaN. Gaps that span missing samples
    are not used. During the first 5 s, NaN is given instead of 0.
    """
    x = np.asarray(ecg, dtype=np.float64)
    out = np.full(int(duration_s), np.nan)
    mask = np.isnan(x)
    if x.size == 0 or mask.all():
        return out
    peaks = detect_beats(x, fs)
    cs = np.concatenate(([0], np.cumsum(mask, dtype=np.int64)))
    win = int(round(WINDOW_S * fs))
    for t in range(int(duration_s)):
        e = min(int(round((t + 1) * fs)), x.size)
        s = max(0, e - win)
        n_win = e - s
        if n_win <= 0:
            continue
        if (cs[e] - cs[s]) / n_win > 0.5:
            continue
        p = peaks[(peaks >= s) & (peaks < e)]
        if p.size >= 2:
            clean = (cs[p[1:]] - cs[p[:-1]]) == 0
            gaps = np.diff(p)[clean]
            if gaps.size:
                out[t] = float(math.floor(60.0 / (np.median(gaps) / fs) + 0.5))
            continue
        if n_win >= win:
            out[t] = 0.0
    return out
