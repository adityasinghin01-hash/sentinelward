"""Ground-truth files: events.jsonl and sent.csv.

Each line goes to the OS in one os.write on an O_APPEND file, so a reader (or a crash)
never sees half a line. Files are fsynced on close.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

EVENT_NAMES = frozenset({
    "run_start", "bed_join", "monitor_alarm", "drift_start", "drift_full", "drift_end",
    "source_end", "run_end", "run_reset",
})


class _LineFile:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._fd: int | None = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)

    def write_line(self, line: str) -> None:
        if self._fd is None:
            raise ValueError(f"{self.path} is closed")
        data = (line + "\n").encode("utf-8")
        view = memoryview(data)
        while view:
            written = os.write(self._fd, view)
            view = view[written:]

    def close(self) -> None:
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


class EventLog:
    """runs/<run_id>/events.jsonl: one ground-truth event per line."""

    def __init__(self, path: str | Path, run_id: str) -> None:
        self.run_id = run_id
        self._file = _LineFile(Path(path))

    def write(self, t_s: float, ts: int, bed_id: str | None, event: str, detail: dict[str, Any] | None = None) -> dict:
        """Append one event line and return it as a dict."""
        if event not in EVENT_NAMES:
            raise ValueError(f"unknown event {event!r}")
        record = {"run_id": self.run_id, "t_s": t_s, "ts": int(ts), "bed_id": bed_id, "event": event,
                  "detail": detail or {}}
        self._file.write_line(json.dumps(record, separators=(",", ":"), allow_nan=False))
        return record

    def close(self) -> None:
        """fsync and close."""
        self._file.close()


class SentLog:
    """runs/<run_id>/sent.csv: one row per second (t_s, sent, max_lag_ms)."""

    HEADER = "t_s,sent,max_lag_ms"

    def __init__(self, path: str | Path) -> None:
        self._file = _LineFile(Path(path))
        self._file.write_line(self.HEADER)

    def row(self, t_s: int, sent: int, max_lag_ms: float | None) -> None:
        """Append one row; max_lag_ms is empty when nothing was sent that second."""
        lag = "" if max_lag_ms is None else f"{max_lag_ms:.1f}"
        self._file.write_line(f"{int(t_s)},{int(sent)},{lag}")

    def close(self) -> None:
        """fsync and close."""
        self._file.close()


def make_run_dir(runs_dir: str | Path, name: str) -> Path:
    """Create runs_dir/name; if it already exists use name__2, name__3, ... (never overwrite)."""
    runs_dir = Path(runs_dir)
    runs_dir.mkdir(parents=True, exist_ok=True)
    candidate, i = runs_dir / name, 2
    while True:
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            candidate = runs_dir / f"{name}__{i}"
            i += 1
