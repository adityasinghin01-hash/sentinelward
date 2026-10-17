"""Clocks: epoch milliseconds UTC. Tests use FakeClock so nothing ever sleeps."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class RealClock:
    def now_ms(self) -> int:
        return time.time_ns() // 1_000_000


class FakeClock:
    def __init__(self, start_ms: int = 1_792_252_800_000) -> None:
        self.t = int(start_ms)

    def now_ms(self) -> int:
        return self.t

    def advance(self, seconds: float) -> int:
        self.t += int(round(seconds * 1000))
        return self.t


def zone(name: str):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def hms(ts_ms: int, tz) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz).strftime("%H:%M:%S")


def hm(ts_ms: int, tz) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz).strftime("%H:%M")


def iso(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts_ms % 1000:03d}Z"


def shift_start_ms(now: int, hhmm: str, tz) -> int:
    """The most recent HH:MM (local) at or before now."""
    h, m = (int(x) for x in hhmm.split(":"))
    local = datetime.fromtimestamp(now / 1000, tz)
    start = local.replace(hour=h, minute=m, second=0, microsecond=0)
    if start > local:
        start = datetime.fromtimestamp(start.timestamp() - 86400, tz).replace(hour=h, minute=m, second=0, microsecond=0)
    return int(start.timestamp() * 1000)
