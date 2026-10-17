"""Time helpers: Unix epoch milliseconds (UTC) and 5-second windows."""

from __future__ import annotations

import time

WINDOW_MS = 5000  # every score, verdict and net_features window starts on a multiple of this


def now_ms() -> int:
    """Return the current Unix time in UTC milliseconds, as an int."""
    return time.time_ns() // 1_000_000


def window_start_for(ts_ms: int) -> int:
    """Return the start (epoch ms) of the 5-second window that ts_ms falls in."""
    if type(ts_ms) is not int:
        raise TypeError(f"window_start_for: ts_ms must be an int of epoch milliseconds, got {type(ts_ms).__name__}")
    # Python's % floors, so this is also correct for negative timestamps.
    return ts_ms - (ts_ms % WINDOW_MS)
