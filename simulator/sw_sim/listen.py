"""listen mode: the web app's Demo button drives runs through ward/demo/control.

The bus handler never blocks: it checks the command, asks any current run to stop at once
on "reset", and queues the command. A controller thread starts and stops runs.
"""

from __future__ import annotations

import logging
import math
import queue
import threading
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .config import check_run_id
from .engine import STOP_RESET, STOP_SHUTDOWN, RunResult, WardRun

log = logging.getLogger("sw_sim.listen")


class ControlError(ValueError):
    """A demo_control message that cannot be obeyed."""


@dataclass(frozen=True)
class ControlCommand:
    """A checked demo_control command."""

    cmd: str
    run_id: str | None
    start_at_s: int


def parse_control(message: Any, run_length_s: int) -> ControlCommand:
    """Check a demo_control message and return the command, or raise ControlError."""
    if not isinstance(message, Mapping):
        raise ControlError("control message is not a JSON object")
    if message.get("type") != "demo_control" or message.get("v") != 1:
        raise ControlError(f"not a v1 demo_control message: type={message.get('type')!r} v={message.get('v')!r}")
    cmd = message.get("cmd")
    if cmd not in ("run", "reset"):
        raise ControlError(f"unknown cmd {cmd!r}")
    run_id = message.get("run_id")
    if cmd == "reset":
        return ControlCommand("reset", run_id if isinstance(run_id, str) else None, 0)
    try:
        check_run_id(run_id)
    except ValueError as exc:
        raise ControlError(str(exc)) from exc
    start_at = message.get("start_at_s", 0)
    if start_at is None:
        start_at = 0
    if isinstance(start_at, bool) or not isinstance(start_at, (int, float)) or not math.isfinite(start_at):
        raise ControlError(f"start_at_s must be a number, got {start_at!r}")
    start = int(math.floor(start_at))
    if not 0 <= start < run_length_s:
        raise ControlError(f"start_at_s {start_at} is outside the run (0..{run_length_s - 1})")
    return ControlCommand("run", run_id, start)


class Controller:
    """Starts a WardRun per "run" command and stops it on "reset" or shutdown."""

    def __init__(self, run_factory: Callable[[str, int], WardRun], run_length_s: int,
                 join_timeout_s: float = 5.0) -> None:
        self._factory = run_factory
        self._run_length_s = run_length_s
        self._join_timeout_s = join_timeout_s
        self._queue: queue.Queue[ControlCommand] = queue.Queue()
        self._lock = threading.Lock()
        self._current: WardRun | None = None
        self._thread: threading.Thread | None = None
        self.results: list[RunResult] = []

    @property
    def current(self) -> WardRun | None:
        """The run in progress, if any."""
        with self._lock:
            return self._current if self._thread is not None and self._thread.is_alive() else None

    def on_message(self, message: Any, topic: str) -> None:
        """Bus handler for ward/demo/control. Never blocks."""
        try:
            command = parse_control(message, self._run_length_s)
        except ControlError as exc:
            log.warning("ignoring control message on %s: %s", topic, exc)
            return
        if command.cmd == "reset":
            run = self.current
            if run is not None:
                run.request_stop(STOP_RESET)
        self._queue.put(command)

    def serve(self, shutdown: threading.Event) -> None:
        """Process commands until shutdown is set, then stop any run (run_end)."""
        try:
            while not shutdown.is_set():
                try:
                    command = self._queue.get(timeout=0.2)
                except queue.Empty:
                    continue
                self._handle(command)
        finally:
            self._stop_current(STOP_SHUTDOWN)

    def _handle(self, command: ControlCommand) -> None:
        if command.cmd == "reset":
            if self._stop_current(STOP_RESET):
                log.info("reset: run stopped; seq counters start again at 1 on the next run")
            else:
                log.info("reset: no run in progress")
            return
        if self._stop_current(STOP_RESET):
            log.info("new run requested: previous run reset")
        try:
            run = self._factory(command.run_id, command.start_at_s)
        except Exception:
            log.exception("could not set up run %s", command.run_id)
            return
        thread = threading.Thread(target=self._run_thread, args=(run,), name=f"ward-{command.run_id}", daemon=True)
        with self._lock:
            self._current, self._thread = run, thread
        thread.start()

    def _run_thread(self, run: WardRun) -> None:
        try:
            self.results.append(run.run())
        except Exception:
            log.exception("run %s failed", run.run_id)

    def _stop_current(self, reason: str) -> bool:
        with self._lock:
            run, thread = self._current, self._thread
        if run is None or thread is None or not thread.is_alive():
            return False
        run.request_stop(reason)
        thread.join(self._join_timeout_s)
        if thread.is_alive():
            log.error("run %s did not stop within %.1f s", run.run_id, self._join_timeout_s)
        with self._lock:
            if self._current is run:
                self._current, self._thread = None, None
        return True
