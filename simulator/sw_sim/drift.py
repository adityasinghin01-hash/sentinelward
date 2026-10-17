"""B08 arterial-line drift: a pure function of the sample time T (seconds since run start)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

DRIFT_CHANNEL = "abp"


@dataclass(frozen=True)
class DriftSpec:
    """Ramp 0 -> peak from ramp_start_s to ramp_end_s, hold until hold_end_s, then 0 at once."""

    bed_id: str
    ramp_start_s: int
    ramp_end_s: int
    hold_end_s: int
    peak_mmHg: float
    channel: str = DRIFT_CHANNEL

    def __post_init__(self) -> None:
        if self.channel != DRIFT_CHANNEL:
            raise ValueError(f"drift may only touch the arterial line ({DRIFT_CHANNEL!r}), got {self.channel!r}")
        if not 0 <= self.ramp_start_s < self.ramp_end_s <= self.hold_end_s:
            raise ValueError(
                "drift times must satisfy 0 <= ramp_start_s < ramp_end_s <= hold_end_s, got "
                f"{self.ramp_start_s}, {self.ramp_end_s}, {self.hold_end_s}"
            )


def offset_at(spec: DriftSpec, t_s: float | np.ndarray) -> float | np.ndarray:
    """Return the drift offset in mmHg at time T = t_s (scalar or array)."""
    t = np.asarray(t_s, dtype=np.float64)
    ramp = spec.peak_mmHg * (t - spec.ramp_start_s) / (spec.ramp_end_s - spec.ramp_start_s)
    out = np.where(
        t < spec.ramp_start_s,
        0.0,
        np.where(t < spec.ramp_end_s, ramp, np.where(t < spec.hold_end_s, spec.peak_mmHg, 0.0)),
    )
    return float(out) if out.ndim == 0 else out


def offsets_for_second(spec: DriftSpec, t_s: int, fs: int) -> np.ndarray:
    """Return the fs per-sample offsets for second t_s; sample i sits at T = t_s + i/fs."""
    return np.asarray(offset_at(spec, t_s + np.arange(fs, dtype=np.float64) / fs), dtype=np.float64)


def drift_events_at(spec: DriftSpec, t_s: int) -> list[tuple[str, dict]]:
    """Return the ground-truth drift events (name, detail) that happen at second t_s."""
    events: list[tuple[str, dict]] = []
    if t_s == spec.ramp_start_s:
        events.append(("drift_start", {
            "channel": spec.channel, "offset_mmHg": 0.0, "ramp_to_mmHg": spec.peak_mmHg,
            "ramp_end_s": spec.ramp_end_s,
        }))
    if t_s == spec.ramp_end_s:
        events.append(("drift_full", {
            "channel": spec.channel, "offset_mmHg": spec.peak_mmHg, "hold_end_s": spec.hold_end_s,
        }))
    if t_s == spec.hold_end_s:
        events.append(("drift_end", {
            "channel": spec.channel, "offset_mmHg": 0.0, "removed_mmHg": spec.peak_mmHg, "reason": "re-zeroed",
        }))
    return events
