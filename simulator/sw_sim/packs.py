"""Bed packs: load <name>.npz + <name>.json and hand out one second at a time.

The npz arrays are float32 little-endian; they are converted to native float64 on load,
so the code is correct on big-endian s390x as well as on x86.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

log = logging.getLogger("sw_sim.packs")

WAVE_CHANNELS = ("ecg", "ppg", "abp")
NUMERIC_CHANNELS = ("hr", "spo2", "rr")


class PackError(ValueError):
    """A bed pack is missing or inconsistent."""


@dataclass(frozen=True)
class Alarm:
    """A monitor alarm recorded in the pack."""

    t_offset_s: float
    code: str
    true_alarm: bool
    priority: str


@dataclass(frozen=True)
class CuffReading:
    """A new non-invasive cuff reading recorded in the pack."""

    t_offset_s: float
    sys: float
    dia: float
    map: float


@dataclass(frozen=True)
class BedPack:
    """One loaded pack. n_seconds counts only full seconds (fs samples on every channel)."""

    name: str
    bed_id: str
    device_id: str
    fs: int
    duration_s: int
    n_seconds: int
    waves: dict[str, np.ndarray]
    numerics: dict[str, np.ndarray]
    cuff_by_second: dict[int, CuffReading]
    alarms_by_second: dict[int, tuple[Alarm, ...]]

    def has(self, channel: str) -> bool:
        """True if the pack carries this waveform channel."""
        return channel in self.waves

    def wave(self, channel: str, p: int) -> np.ndarray | None:
        """The fs samples of pack second p, or None if the channel is absent."""
        arr = self.waves.get(channel)
        if arr is None:
            return None
        return arr[p * self.fs:(p + 1) * self.fs]

    def numeric(self, channel: str, p: int) -> float:
        """The 1 Hz value of pack second p (NaN if missing or absent)."""
        arr = self.numerics.get(channel)
        if arr is None or p >= arr.size:
            return math.nan
        return float(arr[p])


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def load_pack(folder: str | Path, name: str) -> BedPack:
    """Load <folder>/<name>.npz and <folder>/<name>.json."""
    folder = Path(folder)
    npz_path, json_path = folder / f"{name}.npz", folder / f"{name}.json"
    for path in (npz_path, json_path):
        if not path.is_file():
            raise PackError(f"pack file missing: {path}")
    try:
        meta = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PackError(f"{json_path}: {exc}") from exc
    if not isinstance(meta, dict):
        raise PackError(f"{json_path}: must hold a JSON object")
    for key in ("bed_id", "device_id", "fs", "duration_s"):
        if key not in meta:
            raise PackError(f"{json_path}: missing {key!r}")
    if not _finite(meta["fs"]) or not _finite(meta["duration_s"]):
        raise PackError(f"{json_path}: fs and duration_s must be numbers")
    fs = int(meta["fs"])
    duration_s = int(math.floor(float(meta["duration_s"])))
    if fs <= 0 or duration_s <= 0:
        raise PackError(f"{json_path}: fs and duration_s must be positive")

    try:
        with np.load(npz_path, allow_pickle=False) as z:
            arrays = {key: np.asarray(z[key]) for key in z.files}
    except (OSError, ValueError) as exc:
        raise PackError(f"{npz_path}: {exc}") from exc

    waves: dict[str, np.ndarray] = {}
    for ch in WAVE_CHANNELS:
        if ch in arrays and arrays[ch].size > 0:
            if arrays[ch].ndim != 1:
                raise PackError(f"{npz_path}: {ch} must be 1-D, has shape {arrays[ch].shape}")
            waves[ch] = arrays[ch].astype(np.float64)  # '<f4' -> native float64
    numerics: dict[str, np.ndarray] = {}
    for ch in NUMERIC_CHANNELS:
        if ch in arrays and arrays[ch].size > 0:
            numerics[ch] = arrays[ch].reshape(-1).astype(np.float64)

    listed = meta.get("channels")
    if isinstance(listed, list):
        missing = [c for c in listed if c in WAVE_CHANNELS + NUMERIC_CHANNELS and c not in waves and c not in numerics]
        if missing:
            log.warning("pack %s: channels %s listed in json but absent from npz; sent as null", name, missing)

    n_seconds = min([duration_s] + [arr.size // fs for arr in waves.values()])
    if n_seconds <= 0:
        raise PackError(f"pack {name}: no full second of data")
    short = [ch for ch, arr in waves.items() if arr.size < duration_s * fs]
    if short:
        log.warning("pack %s: %s shorter than duration_s=%d; playing %d full seconds", name, short, duration_s, n_seconds)

    cuff_by_second: dict[int, CuffReading] = {}
    nibp = arrays.get("nibp")
    if nibp is not None and nibp.size > 0:
        rows = nibp.astype(np.float64)
        if rows.ndim == 1 and rows.size % 4 == 0:
            rows = rows.reshape(-1, 4)
        if rows.ndim != 2 or rows.shape[1] != 4:
            raise PackError(f"{npz_path}: nibp rows must be [t_offset_s, sys, dia, map], shape {nibp.shape}")
        for t, sys_, dia, map_ in rows.tolist():
            if not math.isfinite(t) or t < 0:
                log.warning("pack %s: nibp row with bad t_offset_s %r skipped", name, t)
                continue
            second = int(math.floor(t))
            if second >= n_seconds:
                continue
            if second in cuff_by_second:
                log.warning("pack %s: second cuff reading in pack second %d skipped", name, second)
                continue
            cuff_by_second[second] = CuffReading(t, sys_, dia, map_)

    alarms: dict[int, list[Alarm]] = {}
    for i, raw in enumerate(meta.get("alarms") or []):
        if not isinstance(raw, dict) or not _finite(raw.get("t_offset_s")) or not isinstance(raw.get("code"), str):
            raise PackError(f"{json_path}: alarms[{i}] needs t_offset_s (number) and code (string)")
        t = float(raw["t_offset_s"])
        second = int(math.floor(t))
        if t < 0 or second >= n_seconds:
            log.warning("pack %s: alarm %s at %.1f s is outside the pack; ignored", name, raw["code"], t)
            continue
        alarms.setdefault(second, []).append(Alarm(
            t_offset_s=t, code=raw["code"], true_alarm=bool(raw.get("true_alarm", False)),
            priority=str(raw.get("priority") or "high"),
        ))

    return BedPack(
        name=name, bed_id=str(meta["bed_id"]), device_id=str(meta["device_id"]), fs=fs,
        duration_s=duration_s, n_seconds=n_seconds, waves=waves, numerics=numerics,
        cuff_by_second=cuff_by_second, alarms_by_second={s: tuple(a) for s, a in alarms.items()},
    )


def load_packs(folder: str | Path, names: Iterable[str]) -> dict[str, BedPack]:
    """Load each named pack once; returns {name: pack}."""
    packs: dict[str, BedPack] = {}
    for name in names:
        if name not in packs:
            packs[name] = load_pack(folder, name)
    return packs
