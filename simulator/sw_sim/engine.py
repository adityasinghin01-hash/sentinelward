"""One ward run: the absolute per-second schedule, message building, and the ground-truth log.

Tick k (T = k seconds) is due at origin_ms + k * 1000, computed from integers every time.
The messages for tick k are built and validated during the idle time before that deadline,
so at the deadline the run only publishes.
"""

from __future__ import annotations

import logging
import math
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol

import numpy as np
import sw_common

from .clock import Clock
from .config import WAVE_CHANNELS, BedEntry, WardScript, format_t
from .drift import DriftSpec, drift_events_at, offset_at, offsets_for_second
from .eventlog import EventLog, SentLog, make_run_dir
from .packs import Alarm, BedPack, CuffReading, PackError

log = logging.getLogger("sw_sim")

PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}

STOP_RESET = "reset"        # demo_control reset -> run_reset
STOP_SIGNAL = "signal"      # Ctrl+C / SIGTERM -> run_end
STOP_SHUTDOWN = "shutdown"  # listen mode shutting down -> run_end


class Publisher(Protocol):
    """Anything with sw_common.Bus's publish(message)."""

    def publish(self, message: dict[str, Any]) -> Any:
        """Send one message."""
        ...


def round_samples(samples: np.ndarray, decimals: int) -> list[float | None]:
    """Round to `decimals` and return a plain list; NaN/inf -> None (sent as null), -0.0 -> 0.0."""
    rounded = np.round(samples, decimals) + 0.0
    values = rounded.tolist()
    if np.isfinite(rounded).all():
        return values
    return [v if math.isfinite(v) else None for v in values]


def to_int(value: float | None) -> int | None:
    """Round half up to int; NaN, inf or None -> None. Zero stays 0."""
    if value is None or not math.isfinite(value):
        return None
    return int(math.floor(value + 0.5))


@dataclass
class _Bed:
    entry: BedEntry
    pack: BedPack
    device_id: str
    drift: DriftSpec | None
    next_seq: int = 1
    sent: int = 0
    sent_any: bool = False
    ended: bool = False

    @property
    def bed_id(self) -> str:
        return self.entry.bed_id

    def pack_second(self, t_s: int) -> int | None:
        """Pack second played at T = t_s, or None before the bed joins."""
        if t_s < self.entry.join_s:
            return None
        return self.entry.pack_start_s + (t_s - self.entry.join_s)


@dataclass
class _Outgoing:
    bed: _Bed
    message: dict[str, Any] | None  # None = failed validation, not sent
    pack_second: int
    alarms: tuple[Alarm, ...]
    alarm_in_message: Alarm | None
    delivered: bool = False
    joined: bool = False


@dataclass(frozen=True)
class TickStat:
    """What happened in one second."""

    t_s: int
    scheduled_ms: int
    sent: int
    invalid: int
    publish_errors: int
    max_lag_ms: float | None
    on_time: int


@dataclass
class RunResult:
    """Summary of a finished run."""

    run_id: str
    run_dir: Path
    status: str  # "complete", "reset", "signal", "shutdown" or "error"
    origin_ms: int
    start_at_s: int
    next_t_s: int
    sent: int
    invalid: int
    publish_errors: int
    lag_p50_ms: float | None
    lag_p99_ms: float | None
    lag_max_ms: float | None
    per_bed_sent: dict[str, int] = field(default_factory=dict)
    ticks: list[TickStat] = field(default_factory=list)
    schedule: list[int] = field(default_factory=list)


class WardRun:
    """Plays a ward script on an absolute schedule and writes the ground-truth log.

    Not reusable: build a new WardRun for every run, so seq counters always start at 1.
    """

    def __init__(
        self,
        script: WardScript,
        packs: Mapping[str, BedPack],
        *,
        run_id: str,
        runs_dir: str | Path,
        clock: Clock,
        bus: Publisher | None,
        start_at_s: int = 0,
        dry_run: bool = False,
        dir_suffix: str = "",
    ) -> None:
        if not 0 <= start_at_s < script.run_length_s:
            raise ValueError(f"start_at {start_at_s} s is outside the run (0..{script.run_length_s - 1})")
        if bus is None and not dry_run:
            raise ValueError("a bus is required unless dry_run is set")
        self.script = script
        self.run_id = run_id
        self.runs_dir = Path(runs_dir)
        self.clock = clock
        self.bus = None if dry_run else bus
        self.start_at_s = int(start_at_s)
        self.dry_run = dry_run
        self.fast = bool(clock.fast) or dry_run
        self._dir_name = run_id + dir_suffix
        self._stop = threading.Event()
        self._stop_reason: str | None = None
        self._lock = threading.Lock()
        self.drift = script.drift
        self.beds: list[_Bed] = []
        seen_devices: dict[str, str] = {}
        for entry in script.beds:
            pack = packs.get(entry.pack_name)
            if pack is None:
                raise PackError(f"no pack loaded for bed {entry.bed_id} (pack {entry.pack_name!r})")
            if pack.fs != script.fs:
                raise PackError(f"pack {pack.name}: fs {pack.fs} != script fs {script.fs}")
            if entry.pack_name == entry.bed_id and pack.bed_id != entry.bed_id:
                raise PackError(f"pack {pack.name}.json says bed_id {pack.bed_id}, script says {entry.bed_id}")
            device_id = entry.device_id or pack.device_id
            if device_id in seen_devices:
                raise ValueError(f"device {device_id} used by both {seen_devices[device_id]} and {entry.bed_id}")
            seen_devices[device_id] = entry.bed_id
            drift = self.drift if self.drift is not None and self.drift.bed_id == entry.bed_id else None
            if drift is not None and not pack.has(drift.channel):
                raise PackError(f"drift bed {entry.bed_id} has no {drift.channel} channel in pack {pack.name}")
            self.beds.append(_Bed(entry=entry, pack=pack, device_id=device_id, drift=drift))
        self.origin_ms: int | None = None
        self.run_dir: Path | None = None
        self.schedule: list[int] = []
        self.ticks: list[TickStat] = []
        self._lags: list[float] = []
        self._sent = 0
        self._invalid = 0
        self._publish_errors = 0

    # ------------------------------------------------------------------ control

    def request_stop(self, reason: str) -> None:
        """Ask the run to stop before its next second (thread- and signal-safe). First reason wins."""
        with self._lock:
            if self._stop_reason is None:
                self._stop_reason = reason
        self._stop.set()

    @property
    def stop_requested(self) -> bool:
        """True once request_stop has been called."""
        return self._stop.is_set()

    # ------------------------------------------------------------------ run

    def run(self) -> RunResult:
        """Play the script from start_at_s to the end (or until stopped). Blocks."""
        L = self.script.run_length_s
        t0 = int(math.ceil(self.clock.now_ms() / 1000.0)) * 1000 + self.script.lead_ms
        origin = t0 - self.start_at_s * 1000
        self.origin_ms = origin
        self.run_dir = make_run_dir(self.runs_dir, self._dir_name)
        events = EventLog(self.run_dir / "events.jsonl", self.run_id)
        sent_log = SentLog(self.run_dir / "sent.csv")
        log.info("run %s: %d beds, %s to %s, first second at epoch %d ms%s%s -> %s",
                 self.run_id, len(self.beds), format_t(self.start_at_s), format_t(L), t0,
                 " (fast)" if self.fast else "", " (dry run)" if self.dry_run else "", self.run_dir)

        started = False
        stopped = False
        error: BaseException | None = None
        k = self.start_at_s
        try:
            while k < L:
                deadline = origin + k * 1000
                pre_events, batch = self._prepare(k, deadline)
                self.schedule.append(deadline)
                if self.clock.wait_until(deadline, self._stop):
                    stopped = True
                    break
                if not started:
                    self._write_run_start(events)
                    started = True
                for bed_id, name, detail in pre_events:
                    events.write(k, deadline, bed_id, name, detail)
                stat = self._send(k, deadline, batch)
                self._write_tick_events(events, k, deadline, batch)
                sent_log.row(k, stat.sent, stat.max_lag_ms)
                self.ticks.append(stat)
                k += 1
            if not stopped:
                stopped = self.clock.wait_until(origin + L * 1000, self._stop)
        except BaseException as exc:
            error = exc
            raise
        finally:
            status = self._finish(events, sent_log, started, stopped, k, error)
        lag50, lag99, lagmax = self._lag_stats()
        log.info("run %s %s at %s: %d sent, %d invalid, %d publish errors, lag p99 %s ms",
                 self.run_id, status, format_t(k), self._sent, self._invalid, self._publish_errors, lag99)
        return RunResult(
            run_id=self.run_id, run_dir=self.run_dir, status=status, origin_ms=origin,
            start_at_s=self.start_at_s, next_t_s=k, sent=self._sent, invalid=self._invalid,
            publish_errors=self._publish_errors, lag_p50_ms=lag50, lag_p99_ms=lag99, lag_max_ms=lagmax,
            per_bed_sent={b.bed_id: b.sent for b in self.beds}, ticks=self.ticks, schedule=self.schedule,
        )

    # ------------------------------------------------------------------ one second

    def _prepare(self, k: int, deadline: int) -> tuple[list[tuple[str, str, dict]], list[_Outgoing]]:
        """Before the deadline: find source ends and build + validate every message of second k."""
        pre_events: list[tuple[str, str, dict]] = []
        batch: list[_Outgoing] = []
        for bed in self.beds:
            if bed.ended:
                continue
            p = bed.pack_second(k)
            if p is None:
                continue
            if p >= bed.pack.n_seconds:
                bed.ended = True
                if bed.sent_any:
                    pre_events.append((bed.bed_id, "source_end", {
                        "device_id": bed.device_id, "pack_second": p, "messages_sent": bed.sent,
                        "last_seq": bed.next_seq - 1,
                    }))
                continue
            batch.append(self._build(bed, k, p, deadline))
        return pre_events, batch

    def _build(self, bed: _Bed, k: int, p: int, deadline: int) -> _Outgoing:
        pack = bed.pack
        waves: dict[str, list[float] | None] = {}
        for ch in WAVE_CHANNELS:
            seg = pack.wave(ch, p)
            if seg is None:
                waves[ch] = None
                continue
            if bed.drift is not None and ch == bed.drift.channel:
                seg = seg + offsets_for_second(bed.drift, k, pack.fs)
            waves[ch] = round_samples(seg, self.script.rounding[ch])

        nibp = None
        reading = pack.cuff_by_second.get(p)
        if reading is not None:
            nibp = _cuff(reading, deadline + int(round((reading.t_offset_s - p) * 1000)), bed.bed_id, k)

        alarms: tuple[Alarm, ...] = () if bed.entry.suppress_alarms else pack.alarms_by_second.get(p, ())
        chosen = min(alarms, key=lambda a: PRIORITY_RANK.get(a.priority, len(PRIORITY_RANK))) if alarms else None

        message: dict[str, Any] | None
        try:
            message = sw_common.make_vitals(
                bed_id=bed.bed_id, device_id=bed.device_id, seq=bed.next_seq, ts=int(deadline), fs=pack.fs,
                ecg=waves["ecg"], ppg=waves["ppg"], abp=waves["abp"],
                hr=to_int(pack.numeric("hr", p)), spo2=to_int(pack.numeric("spo2", p)),
                rr=to_int(pack.numeric("rr", p)), nibp=nibp,
                monitor_alarm=None if chosen is None else {"code": chosen.code, "priority": chosen.priority},
            )
            errors = list(sw_common.validate(message))
        except Exception as exc:  # make_vitals refusing its input counts as invalid too
            message, errors = None, [f"make_vitals: {exc}"]
        if errors:
            log.warning("skipping invalid message %s seq %d at %s (pack second %d): %s",
                        bed.bed_id, bed.next_seq, format_t(k), p, "; ".join(errors))
            message = None
        return _Outgoing(bed=bed, message=message, pack_second=p, alarms=alarms, alarm_in_message=chosen)

    def _send(self, k: int, deadline: int, batch: list[_Outgoing]) -> TickStat:
        """At the deadline: publish, commit seq, measure lag."""
        sent = invalid = errors = on_time = 0
        max_lag: float | None = None
        budget = self.script.lag_budget_ms
        first_error = ""
        for out in batch:
            if out.message is None:
                invalid += 1
                continue
            if self.bus is not None:
                try:
                    accepted = self.bus.publish(out.message)
                except Exception as exc:
                    accepted, first_error = False, first_error or f"{out.bed.bed_id}: {exc}"
                if accepted is False:  # sw_common.Bus returns False when a QoS 0 message is dropped
                    errors += 1
                    first_error = first_error or f"{out.bed.bed_id}: dropped (hub not connected?)"
                    continue
            lag = (self.clock.now_ms() - deadline) / self.clock.speed
            self._lags.append(lag)
            bed = out.bed
            bed.next_seq += 1
            bed.sent += 1
            if not bed.sent_any:
                bed.sent_any = True
                out.joined = True
            out.delivered = True
            sent += 1
            if lag <= budget:
                on_time += 1
            max_lag = lag if max_lag is None else max(max_lag, lag)
        if errors:
            log.error("%s: %d message(s) not sent, e.g. %s", format_t(k), errors, first_error)
        self._sent += sent
        self._invalid += invalid
        self._publish_errors += errors
        return TickStat(t_s=k, scheduled_ms=deadline, sent=sent, invalid=invalid, publish_errors=errors,
                        max_lag_ms=max_lag, on_time=on_time)

    def _write_tick_events(self, events: EventLog, k: int, deadline: int, batch: list[_Outgoing]) -> None:
        for out in batch:
            bed = out.bed
            if out.joined:
                events.write(k, deadline, bed.bed_id, "bed_join", {
                    "device_id": bed.device_id, "pack_second": out.pack_second,
                    "scheduled_join_s": bed.entry.join_s, "seq": out.message["seq"] if out.message else None,
                })
            for alarm in out.alarms:
                events.write(k, deadline, bed.bed_id, "monitor_alarm", {
                    "code": alarm.code, "true_alarm": alarm.true_alarm, "priority": alarm.priority,
                    "device_id": bed.device_id, "pack_second": out.pack_second, "t_offset_s": alarm.t_offset_s,
                    "in_message": alarm is out.alarm_in_message, "delivered": out.delivered,
                })
        if self.drift is not None:
            for name, detail in drift_events_at(self.drift, k):
                events.write(k, deadline, self.drift.bed_id, name, detail)

    # ------------------------------------------------------------------ start / finish

    def _write_run_start(self, events: EventLog) -> None:
        assert self.origin_ms is not None
        beds: dict[str, dict] = {}
        for bed in self.beds:
            p = bed.pack_second(self.start_at_s)
            beds[bed.bed_id] = {
                "device_id": bed.device_id, "pack": bed.pack.name, "join_s": bed.entry.join_s,
                "pack_start_s": bed.entry.pack_start_s, "pack_seconds": bed.pack.n_seconds,
                "pack_second_at_start": p if p is not None and p < bed.pack.n_seconds else None,
                "state_at_start": "waiting" if p is None else ("sending" if p < bed.pack.n_seconds else "ended"),
            }
        drift = None
        if self.drift is not None:
            drift = {"bed_id": self.drift.bed_id, "channel": self.drift.channel,
                     "offset_mmHg_at_start": round(float(offset_at(self.drift, self.start_at_s)), 3)}
        events.write(self.start_at_s, self.origin_ms + self.start_at_s * 1000, None, "run_start", {
            "start_at_s": self.start_at_s, "run_length_s": self.script.run_length_s, "origin_ms": self.origin_ms,
            "fast": self.fast, "speed": self.clock.speed, "dry_run": self.dry_run, "beds": beds, "drift": drift,
        })

    def _lag_stats(self) -> tuple[float | None, float | None, float | None]:
        if not self._lags:
            return None, None, None
        arr = np.asarray(self._lags)
        p50, p99 = np.percentile(arr, [50, 99])
        return round(float(p50), 2), round(float(p99), 2), round(float(arr.max()), 2)

    def _finish(self, events: EventLog, sent_log: SentLog, started: bool, stopped: bool, k: int,
                error: BaseException | None) -> str:
        assert self.origin_ms is not None
        if error is not None:
            status = "error"
        elif stopped:
            status = self._stop_reason or STOP_SIGNAL
        else:
            status = "complete"
        lag50, lag99, lagmax = self._lag_stats()
        detail: dict[str, Any] = {
            "reason": status, "next_t_s": k, "fast": self.fast, "dry_run": self.dry_run,
            "messages_sent": self._sent, "invalid": self._invalid, "publish_errors": self._publish_errors,
            "lag_p50_ms": lag50, "lag_p99_ms": lag99, "lag_max_ms": lagmax,
            "per_bed_sent": {b.bed_id: b.sent for b in self.beds},
        }
        if error is not None:
            detail["error"] = repr(error)
        try:
            if not started:
                self._write_run_start(events)
            if status == "complete":
                L = self.script.run_length_s
                events.write(L, self.origin_ms + L * 1000, None, "run_end", detail)
            else:
                now = self.clock.now_ms()
                t_s = round((now - self.origin_ms) / 1000.0, 3)
                events.write(t_s, int(now), None, "run_reset" if status == STOP_RESET else "run_end", detail)
        finally:
            try:
                events.close()
            finally:
                sent_log.close()
        return status


def _cuff(reading: CuffReading, ts_ms: int, bed_id: str, k: int) -> dict[str, Any] | None:
    values = {"sys": to_int(reading.sys), "dia": to_int(reading.dia), "map": to_int(reading.map)}
    if all(v is None for v in values.values()):
        log.warning("cuff reading for %s at %s has no values; nibp left null", bed_id, format_t(k))
        return None
    return {**values, "ts": int(ts_ms)}
