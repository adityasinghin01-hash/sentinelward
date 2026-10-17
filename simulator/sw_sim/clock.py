"""Clocks for the absolute schedule: real time, virtual fast time, and instant (dry-run) time.

Every clock reports wall-aligned epoch milliseconds and can wait until an absolute target,
returning early (True) the moment a stop event is set.
"""

from __future__ import annotations

import threading
import time
from typing import Protocol

_MAX_WAIT_CHUNK_S = 0.25  # wake at least this often, so signals and stops are seen quickly


class Clock(Protocol):
    """What the ward run needs from a clock."""

    speed: float  # virtual ms per real ms (1.0 = real time)
    fast: bool    # True if ts values are virtual, not real wall-clock time

    def now_ms(self) -> float:
        """Current time in epoch milliseconds (UTC)."""
        ...

    def wait_until(self, target_ms: float, stop: threading.Event) -> bool:
        """Block until now_ms() >= target_ms. Return True if stop was set first."""
        ...


class RealClock:
    """Wall-clock epoch ms, measured with the monotonic clock and one fixed offset.

    The offset is taken once at construction, so NTP steps during a run cannot bend the
    schedule. Waits sleep until SPIN_MS before the target, then spin for precision.
    """

    SPIN_MS = 2.0
    speed = 1.0
    fast = False

    def __init__(self) -> None:
        self._offset_ns = time.time_ns() - time.monotonic_ns()

    def now_ms(self) -> float:
        """Current wall-aligned epoch ms."""
        return (time.monotonic_ns() + self._offset_ns) / 1e6

    def wait_until(self, target_ms: float, stop: threading.Event) -> bool:
        """Sleep, then spin, until target_ms; return True if stop is set first."""
        while True:
            if stop.is_set():
                return True
            remaining = target_ms - self.now_ms()
            if remaining <= 0:
                return False
            if remaining > self.SPIN_MS:
                if stop.wait(min((remaining - self.SPIN_MS) / 1000.0, _MAX_WAIT_CHUNK_S)):
                    return True
            else:
                time.sleep(0)


class VirtualClock:
    """Virtual time running `speed` times faster than real time (self-tests only)."""

    fast = True

    def __init__(self, speed: float) -> None:
        if speed <= 1.0:
            raise ValueError("VirtualClock is only for speed > 1")
        self.speed = float(speed)
        self._base_wall_ms = time.time_ns() / 1e6
        self._base_mono_ns = time.monotonic_ns()

    def now_ms(self) -> float:
        """Virtual epoch ms: start wall time + elapsed real time x speed."""
        return self._base_wall_ms + (time.monotonic_ns() - self._base_mono_ns) / 1e6 * self.speed

    def wait_until(self, target_ms: float, stop: threading.Event) -> bool:
        """Wait (target - now) / speed real seconds; return True if stop is set first."""
        while True:
            if stop.is_set():
                return True
            remaining_real_s = (target_ms - self.now_ms()) / self.speed / 1000.0
            if remaining_real_s <= 0:
                return False
            if stop.wait(min(remaining_real_s, _MAX_WAIT_CHUNK_S)):
                return True


class InstantClock:
    """Jumps straight to each target (dry-run): the whole script runs as fast as it can be built."""

    speed = 1.0
    fast = True

    def __init__(self, start_ms: float | None = None) -> None:
        self._now = float(time.time_ns() / 1e6 if start_ms is None else start_ms)

    def now_ms(self) -> float:
        """Current virtual epoch ms."""
        return self._now

    def wait_until(self, target_ms: float, stop: threading.Event) -> bool:
        """Advance to target_ms at once; return True if stop is set."""
        if stop.is_set():
            return True
        self._now = max(self._now, float(target_ms))
        return False


def make_clock(speed: float, dry_run: bool) -> Clock:
    """Pick the clock for a command-line run."""
    if speed < 1.0:
        raise ValueError(f"--speed must be >= 1, got {speed}")
    if dry_run:
        return InstantClock()
    if speed == 1.0:
        return RealClock()
    return VirtualClock(speed)
