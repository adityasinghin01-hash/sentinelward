"""In-memory ward state: per-bed buffers, trust and isolation, alerts, actions, records and the
never-blank display rule (safety rule 1).

Everything here runs on the asyncio event loop thread only, so no locks are needed.
"""

from __future__ import annotations

import copy
from bisect import bisect_right
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterable

from sw_common import device_for_bed

from .config import BedConfig, Clock, WardConfig

if TYPE_CHECKING:
    from .store import WarmStart

BUFFER_S = 1800  # per-second points kept per bed: 30 min (the rule needs 10; history needs 30)
OFFLINE_AFTER_S = 5.0  # no vitals for this long => display "offline"
RECENT_VERDICTS = 10
MAX_ACTIONS = 5000
MAX_ALERTS = 10000
MAX_RECORDS = 10000
NET_BUFFER = 360  # net_features rows per device: 30 min at one per 5 s
WAVE_BUFFER = 60  # thin live waveforms, separate from the 30-minute scalar history

ISOLATING_ACTIONS = frozenset({"disable_client", "set_bed_untrusted"})
FAILED_RESULTS = frozenset({"failed", "error"})  # such an action is not in force
OPEN_ALERT_STATUSES = ("open", "escalated")  # not yet acknowledged or closed
PRIORITY_RANK = {"high": 3, "medium": 2, "low": 1, "none": 0}

LIVE, LAST_TRUSTED, OFFLINE = "live", "last_trusted", "offline"


# --------------------------------------------------------------------------- small helpers

def abp_mean(abp: list | None) -> float | None:
    """Mean of the non-null ABP samples, or None without an arterial line."""
    if not abp:
        return None
    vals = [x for x in abp if x is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def thin_wave(samples: list | None, step: int = 5) -> list | None:
    """Downsample 125 Hz to 25 Hz by averaging each group of 5 samples (null groups stay null)."""
    if samples is None:
        return None
    out: list[float | None] = []
    for i in range(0, len(samples), step):
        chunk = [x for x in samples[i:i + step] if x is not None]
        out.append(round(sum(chunk) / len(chunk), 4) if chunk else None)
    return out


@dataclass(slots=True)
class Point:
    """One per-second sample of a bed (no waveforms)."""

    ts: int
    received_ms: int
    seq: int | None
    hr: float | None
    spo2: float | None
    rr: float | None
    sys: float | None  # sys/dia/map/nibp_ts: only in the second a new cuff reading arrived
    dia: float | None
    map: float | None
    nibp_ts: int | None
    abp_mean: float | None
    alarm_code: str | None
    alarm_priority: str | None
    verdict: str | None
    trusted: bool
    bp: dict | None  # the newest cuff reading known at this second: {sys, dia, map, ts}

    def latest(self) -> dict[str, Any]:
        """The values shown on a bed tile."""
        return {"ts": self.ts, "hr": self.hr, "spo2": self.spo2, "rr": self.rr,
                "bp": dict(self.bp) if self.bp is not None else None, "abp_mean": self.abp_mean}

    def history_point(self) -> dict[str, Any]:
        """One point of /api/beds/<id>/history."""
        return {"ts": self.ts, "hr": self.hr, "spo2": self.spo2, "rr": self.rr, "sys": self.sys,
                "dia": self.dia, "map": self.map, "abp_mean": self.abp_mean, "verdict": self.verdict,
                "trusted": self.trusted}


def point_from_row(row: dict[str, Any], bp: dict | None) -> Point:
    """Build a Point from a vitals_1s row; bp is the newest cuff reading at or before it."""
    if row.get("nibp_ts") is not None:
        bp = {"sys": row.get("sys"), "dia": row.get("dia"), "map": row.get("map"), "ts": row["nibp_ts"]}
    return Point(ts=row["ts"], received_ms=row.get("received_ts") or row["ts"], seq=row.get("seq"),
                 hr=row.get("hr"), spo2=row.get("spo2"), rr=row.get("rr"), sys=row.get("sys"),
                 dia=row.get("dia"), map=row.get("map"), nibp_ts=row.get("nibp_ts"),
                 abp_mean=row.get("abp_mean"), alarm_code=row.get("alarm_code"),
                 alarm_priority=row.get("alarm_priority"), verdict=row.get("verdict"),
                 trusted=bool(row.get("trusted", False)), bp=bp)


@dataclass(slots=True)
class View:
    """What a bed shows right now, after the never-blank rule."""

    display: str
    latest: dict | None
    latest_trusted: bool | None  # False only when no trusted point exists to show
    last_trusted_ts: int | None
    offline_since: int | None


@dataclass(slots=True)
class TrustMark:
    """Points of bed_id with after_ts < ts <= upto_ts turned out to be untrusted."""

    bed_id: str
    after_ts: int
    upto_ts: int


class BedState:
    """Everything kept in memory for one bed."""

    def __init__(self, cfg: BedConfig) -> None:
        self.cfg = cfg
        self.points: deque[Point] = deque(maxlen=BUFFER_S)
        self.last_point: Point | None = None
        self.last_rx_mono: float | None = None
        self.last_rx_ms: int | None = None
        self.verdict: dict | None = None
        self.recent_verdicts: deque[dict] = deque(maxlen=RECENT_VERDICTS)
        self.scores: dict[str, dict] = {}
        self.alarm: dict | None = None
        self.manual: dict | None = None
        self.last_bedside: dict | None = None
        # From ward.yaml until staff assign someone on a screen: {clinician_id, staff_id, status, ts, by}.
        self.assignment: dict[str, Any] | None = ({"clinician_id": cfg.nurse, "staff_id": cfg.nurse,
                                                   "status": "assigned", "ts": None, "by": None}
                                                  if cfg.nurse else None)
        self.nurse_call: dict | None = None
        self.pin_key: tuple[int, bool] | None = None  # (cutoff, inclusive) the cached pin was found for
        self.pin: Point | None = None
        self.signature: tuple | None = None  # last state pushed as bed_state
        self.display: str = OFFLINE
        self.last_thin_s: int | None = None
        self.thin_waves: OrderedDict[int, dict[str, list]] = OrderedDict()
        self.trusted_wave_ts: int | None = None
        self.trusted_wave: dict[str, list] | None = None
        # Historical source-time ranges remain unsafe even after the monitor recovers.
        # Ranges use the same (after_ts, upto_ts] convention as TrustMark.
        self.untrusted_intervals: list[tuple[int, int]] = []
        self.untrusted_after_ts: int | None = None
        self.untrusted_upto_ts: int | None = None


class DeviceState:
    """One monitor: isolation in force, last contact and network features."""

    def __init__(self, device_id: str, bed_id: str) -> None:
        self.device_id = device_id
        self.bed_id = bed_id
        self.isolations: dict[str, int] = {}  # action_id -> action ts, for isolations still in force
        self.last_seen_ms: int | None = None
        self.last_seen_mono: float | None = None
        self.net: dict | None = None
        self.net_rows: deque[dict] = deque(maxlen=NET_BUFFER)

    def isolated_since(self) -> int | None:
        """Moment the earliest isolation still in force started, or None."""
        return min(self.isolations.values()) if self.isolations else None


# --------------------------------------------------------------------------- ward state

class WardState:
    """The live ward. Ingest methods take validated messages; read methods return JSON-ready dicts."""

    def __init__(self, ward: WardConfig, clock: Clock) -> None:
        self.ward = ward
        self.clock = clock
        self._init_data()

    def _init_data(self) -> None:
        self.beds: dict[str, BedState] = {b.bed_id: BedState(b) for b in self.ward.beds}
        self.devices: dict[str, DeviceState] = {b.device_id: DeviceState(b.device_id, b.bed_id)
                                                for b in self.ward.beds}
        self.alerts: OrderedDict[str, dict] = OrderedDict()
        self.actions: OrderedDict[str, dict] = OrderedDict()
        self.records: OrderedDict[str, dict] = OrderedDict()
        self._iso_device: dict[str, str] = {}  # isolating action_id -> device_id
        self._enabled: dict[str, tuple[str, dict[str, int]]] = {}  # enable action_id -> what it cleared
        self._applied: set[str] = set()  # action_ids whose effect is in force
        self._undone: dict[str, tuple] = {}  # undo action_id -> what it reversed (for a late failure)
        self._lookups: dict[tuple[str, int, bool], None] = {}
        self._lookups_in_flight: set[tuple[str, int, bool]] = set()
        self.last_message_ms: int | None = None
        for bed in self.beds.values():
            bed.signature = self._signature(bed, self._view(bed))

    def reset(self) -> None:
        """Forget all run data (keeps the ward configuration)."""
        self._init_data()

    # ------------------------------------------------------------------ trust

    def _untrusted_cutoff(self, bed: BedState) -> tuple[int, bool, int] | None:
        """(cutoff, inclusive, shown last_trusted_ts) when the bed is not trusted, else None."""
        lt = bed.verdict.get("last_trusted_ts") if bed.verdict is not None else None
        iso = self.devices[bed.cfg.device_id].isolated_since()
        boundaries = []
        if lt is not None:
            boundaries.append((lt, True, lt))
        if iso is not None:
            boundaries.append((iso, False, iso))
        return min(boundaries) if boundaries else None

    def _pin(self, bed: BedState, cutoff: int, inclusive: bool) -> Point | None:
        """Newest point at (or strictly before) cutoff; asks the store when it is older than the buffer."""
        key = (cutoff, inclusive)
        if bed.pin_key == key and bed.pin is not None and bed.pin.trusted:
            return bed.pin
        pts = bed.points
        if pts:
            idx = bisect_right(pts, cutoff if inclusive else cutoff - 1, key=lambda p: p.ts)
            for i in range(idx - 1, -1, -1):
                if pts[i].trusted:
                    bed.pin_key, bed.pin = key, pts[i]
                    self._remember_trusted_wave(bed, bed.pin)
                    return bed.pin
        if bed.pin_key == key:
            return None  # the database already answered: no trusted point exists
        # Nothing in the buffer is old enough: look it up in the database (done by the ticker).
        lk = (bed.cfg.bed_id, cutoff, inclusive)
        if lk not in self._lookups_in_flight:
            self._lookups[lk] = None
        if bed.pin is not None and bed.pin.trusted and (bed.pin.ts <= cutoff if inclusive else bed.pin.ts < cutoff):
            return bed.pin
        return None

    def take_pin_lookups(self) -> list[tuple[str, int, bool]]:
        """Pending "newest point at or before" lookups for the store; marks them in flight."""
        out = list(self._lookups)
        self._lookups.clear()
        self._lookups_in_flight.update(out)
        return out

    def set_pin(self, bed_id: str, cutoff: int, inclusive: bool, point: Point | None) -> None:
        """Store the result of a lookup (None = no trusted point exists)."""
        self._lookups_in_flight.discard((bed_id, cutoff, inclusive))
        bed = self.beds.get(bed_id)
        if bed is not None:
            if point is not None and (not point.trusted or self._timestamp_untrusted(bed, point.ts) or
                    not (point.ts <= cutoff if inclusive else point.ts < cutoff)):
                point = None
            bed.pin_key, bed.pin = (cutoff, inclusive), point
            if point is not None:
                self._remember_trusted_wave(bed, point)

    def trusted_now(self, bed: BedState) -> bool:
        """A verdict exists, it is trusted, and no isolation is in force."""
        return self._trusted_now(bed)

    def _trusted_now(self, bed: BedState) -> bool:
        return bed.verdict is not None and self._untrusted_cutoff(bed) is None

    @staticmethod
    def _timestamp_untrusted(bed: BedState, ts: int) -> bool:
        if bed.untrusted_after_ts is not None and ts > bed.untrusted_after_ts:
            return True
        return any(after < ts <= upto for after, upto in bed.untrusted_intervals)

    def _sync_trust_interval(self, bed: BedState, event_ts: int) -> TrustMark | None:
        """Track continuous loss of trust across overlapping verdicts and isolations."""
        cutoff = self._untrusted_cutoff(bed)
        if cutoff is not None:
            after = cutoff[0] if cutoff[1] else cutoff[0] - 1
            bed.untrusted_after_ts = (after if bed.untrusted_after_ts is None
                                      else min(after, bed.untrusted_after_ts))
            bed.untrusted_upto_ts = max(event_ts, bed.untrusted_upto_ts or event_ts,
                                        bed.last_point.ts if bed.last_point else event_ts)
            return self._mark_untrusted(bed, bed.untrusted_after_ts, bed.untrusted_upto_ts)
        if bed.untrusted_after_ts is not None:
            # A new point at the recovery timestamp is trusted. An already observed
            # untrusted source timestamp stays rejected, including future-dated samples.
            upto = max(event_ts - 1, bed.untrusted_upto_ts or event_ts - 1)
            ranges = sorted([*bed.untrusted_intervals, (bed.untrusted_after_ts, upto)])
            merged: list[tuple[int, int]] = []
            for after, end in ranges:
                if after >= end:
                    continue
                if merged and after <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(merged[-1][1], end))
                else:
                    merged.append((after, end))
            bed.untrusted_intervals = merged
            bed.untrusted_after_ts, bed.untrusted_upto_ts = None, None
        return None

    def _view(self, bed: BedState) -> View:
        cut = self._untrusted_cutoff(bed)
        shown_lt = cut[2] if cut is not None else None
        if bed.last_point is None:
            return View(OFFLINE, None, None, shown_lt, None)
        offline = (self.clock.mono() - (bed.last_rx_mono or 0.0)) > OFFLINE_AFTER_S
        if cut is None:
            point, trusted = bed.last_point, self._trusted_now(bed) and bed.last_point.trusted
        else:
            pin = self._pin(bed, cut[0], cut[1])
            # No trusted point at all: show the last values, flagged, rather than a blank bed.
            point, trusted = (pin, True) if pin is not None else (bed.last_point, False)
        if offline:
            return View(OFFLINE, point.latest(), trusted, shown_lt, bed.last_rx_ms)
        return View(LIVE if cut is None else LAST_TRUSTED, point.latest(), trusted, shown_lt, None)

    def view(self, bed_id: str) -> View:
        """Current view of one bed."""
        return self._view(self.beds[bed_id])

    @staticmethod
    def _signature(bed: BedState, v: View) -> tuple:
        frozen_ts = v.latest["ts"] if (v.latest is not None and v.display != LIVE) else None
        return (v.display, v.last_trusted_ts, frozen_ts, v.offline_since, v.latest_trusted)

    def changes(self, bed_ids: Iterable[str] | None = None) -> list[dict]:
        """bed_state messages for beds whose display (or frozen values) changed since the last call."""
        out: list[dict] = []
        now = self.clock.ms()
        for bed_id in (self.beds if bed_ids is None else bed_ids):
            bed = self.beds.get(bed_id)
            if bed is None:
                continue
            v = self._view(bed)
            sig = self._signature(bed, v)
            if sig != bed.signature:
                out.append({"type": "bed_state", "bed_id": bed_id, "ts": now, "display": v.display,
                            "previous": bed.display, "latest": v.latest, "latest_trusted": v.latest_trusted,
                            "last_trusted_ts": v.last_trusted_ts, "offline_since": v.offline_since})
                bed.signature = sig
                bed.display = v.display
        return out

    def _mark_untrusted(self, bed: BedState, after_ts: int, upto_ts: int) -> TrustMark | None:
        """Flag buffered points newer than after_ts as untrusted; return a mark for the database."""
        for p in reversed(bed.points):
            if p.ts <= after_ts:
                break
            if p.trusted:
                p.trusted = False
        if bed.pin is not None and bed.pin.ts > after_ts:
            bed.pin.trusted = False
            bed.pin_key = None
        if bed.trusted_wave_ts is not None and bed.trusted_wave_ts > after_ts:
            bed.trusted_wave_ts, bed.trusted_wave = None, None
        upto_ts = max(upto_ts, bed.last_point.ts if bed.last_point is not None else upto_ts)
        if upto_ts > after_ts:
            return TrustMark(bed.cfg.bed_id, after_ts, upto_ts)
        return None

    # ------------------------------------------------------------------ ingest

    def on_vitals(self, msg: dict) -> tuple[Point, bool] | None:
        """Add one vitals message; returns (point, is_newest) or None for a bed not on this ward."""
        bed = self.beds.get(msg["bed_id"])
        if bed is None:
            return None
        now_ms, now_mono = self.clock.ms(), self.clock.mono()
        prev = bed.last_point
        nibp = msg.get("nibp")
        alarm = msg.get("monitor_alarm")
        trusted = self._trusted_now(bed) and not self._timestamp_untrusted(bed, msg["ts"])
        if bed.untrusted_after_ts is not None:
            bed.untrusted_upto_ts = max(msg["ts"], bed.untrusted_upto_ts or msg["ts"])
        point = Point(
            ts=msg["ts"], received_ms=now_ms, seq=msg.get("seq"), hr=msg.get("hr"), spo2=msg.get("spo2"),
            rr=msg.get("rr"),
            sys=nibp.get("sys") if nibp else None, dia=nibp.get("dia") if nibp else None,
            map=nibp.get("map") if nibp else None, nibp_ts=nibp.get("ts") if nibp else None,
            abp_mean=abp_mean(msg.get("abp")),
            alarm_code=alarm.get("code") if alarm else None,
            alarm_priority=alarm.get("priority") if alarm else None,
            verdict=bed.verdict.get("verdict") if bed.verdict else None,
            trusted=trusted,
            bp=None,
        )
        newest = prev is None or point.ts >= prev.ts
        sec = point.ts // 1000
        idx = bisect_right(bed.points, sec, key=lambda p: p.ts // 1000)
        same = bed.points[idx - 1] if idx and bed.points[idx - 1].ts // 1000 == sec else None
        accepted = same is None or (point.ts, point.seq or 0) > (same.ts, same.seq or 0)
        if accepted:
            before = same if same is not None else (bed.points[idx - 1] if idx else None)
            point.bp = dict(before.bp) if before is not None and before.bp is not None else None
            if nibp and (point.bp is None or point.nibp_ts >= point.bp["ts"]):
                point.bp = {"sys": point.sys, "dia": point.dia, "map": point.map, "ts": point.nibp_ts}
            if same is not None:
                bed.points[idx - 1] = point
                bed.thin_waves.pop(same.ts, None)
            elif len(bed.points) == bed.points.maxlen:
                if idx > 0:
                    bed.points.popleft()
                    bed.points.insert(idx - 1, point)
            else:
                bed.points.insert(idx, point)
            # A late cuff measurement also applies to later scalar points until the next cuff.
            if point.bp is not None:
                following = bisect_right(bed.points, point.ts, key=lambda p: p.ts)
                for later in list(bed.points)[following:]:
                    if later.bp is None or later.bp["ts"] < point.bp["ts"]:
                        later.bp = dict(point.bp)
                    else:
                        break
            if newest:
                bed.last_point = point
                bed.alarm = dict(alarm) if alarm else None
            bed.thin_waves[point.ts] = {channel: thin_wave(msg.get(channel)) or []
                                        for channel in ("ecg", "ppg", "abp")}
            while len(bed.thin_waves) > WAVE_BUFFER:
                bed.thin_waves.popitem(last=False)
            if trusted and self._untrusted_cutoff(bed) is None:
                self._remember_trusted_wave(bed, point)
            if bed.pin_key is not None and point.ts <= bed.pin_key[0]:
                bed.pin_key = None  # a new value at or before the cutoff arrived late
        else:
            point, newest = same, False
        bed.last_rx_ms, bed.last_rx_mono = now_ms, now_mono
        dev = self.devices[bed.cfg.device_id]
        dev.last_seen_ms, dev.last_seen_mono = now_ms, now_mono
        self.last_message_ms = now_ms
        return point, newest

    @staticmethod
    def _remember_trusted_wave(bed: BedState, point: Point) -> None:
        wave = bed.thin_waves.get(point.ts)
        if point.trusted and wave is not None:
            bed.trusted_wave_ts = point.ts
            bed.trusted_wave = copy.deepcopy(wave)

    def waveform(self, bed_id: str, ts: int | None = None, *, trusted: bool = False) -> dict[str, list]:
        """Thin samples for exactly one scalar timestamp; absent channels remain empty.

        The frozen trusted waveform has its own slot so live untrusted telemetry cannot evict it.
        Persisted scalar pins without samples deliberately have empty waveform channels.
        """
        bed = self.beds[bed_id]
        if ts is None:
            view = self._view(bed)
            ts = view.latest["ts"] if view.latest is not None else None
        empty = {"ecg": [], "ppg": [], "abp": []}
        if ts is None:
            return empty
        if trusted:
            if bed.trusted_wave_ts == ts and bed.trusted_wave is not None:
                return copy.deepcopy(bed.trusted_wave)
            point = next((p for p in reversed(bed.points) if p.ts == ts), None)
            if point is None or not point.trusted:
                return empty
            self._remember_trusted_wave(bed, point)
        return copy.deepcopy(bed.thin_waves.get(ts, empty))

    def thin_message(self, bed_id: str, msg: dict) -> dict | None:
        """The vitals_thin push for this vitals message (at most one per bed per second).

        When the bed is not live, the numbers are the frozen trusted values and the waveforms are null:
        untrusted numbers are never pushed to bed screens.
        """
        bed = self.beds[bed_id]
        sec = msg["ts"] // 1000
        if bed.last_thin_s is not None and sec <= bed.last_thin_s:
            return None
        bed.last_thin_s = sec
        v = self._view(bed)
        if v.display == LIVE:
            return {"type": "vitals_thin", "bed_id": bed_id, "ts": msg["ts"], "hr": msg.get("hr"),
                    "spo2": msg.get("spo2"), "rr": msg.get("rr"), "nibp": msg.get("nibp"),
                    "ecg_25hz": thin_wave(msg.get("ecg")), "ppg_25hz": thin_wave(msg.get("ppg")),
                    "display": v.display, "latest_trusted": v.latest_trusted}
        latest = v.latest or {}
        return {"type": "vitals_thin", "bed_id": bed_id, "ts": latest.get("ts"), "hr": latest.get("hr"),
                "spo2": latest.get("spo2"), "rr": latest.get("rr"), "nibp": latest.get("bp"),
                "ecg_25hz": None, "ppg_25hz": None, "display": v.display,
                "latest_trusted": v.latest_trusted}

    def on_score(self, msg: dict) -> bool:
        """Keep the newest score per bed and model."""
        bed = self.beds.get(msg["bed_id"])
        self.last_message_ms = self.clock.ms()
        if bed is None:
            return False
        cur = bed.scores.get(msg["model"])
        if cur is None or msg["window_start"] >= cur["window_start"]:
            bed.scores[msg["model"]] = msg
        return True

    def on_verdict(self, msg: dict) -> tuple[bool, TrustMark | None]:
        """Apply a verdict; returns (became the latest, trust mark for the database)."""
        bed = self.beds.get(msg["bed_id"])
        self.last_message_ms = self.clock.ms()
        if bed is None:
            return False, None
        if bed.verdict is not None and msg["ts"] < bed.verdict["ts"]:
            return False, None
        bed.verdict = msg
        bed.recent_verdicts.appendleft(msg)
        mark = self._sync_trust_interval(bed, msg["ts"])
        return True, mark

    def on_action(self, msg: dict) -> tuple[bool, list[TrustMark]]:
        """Apply an action (isolation bookkeeping); returns (new or changed action, trust marks).

        Agents publish the same action_id again when its result changes (pending -> ok/failed):
        the newest version replaces the stored one, and a late failure reverses the effect.
        """
        self.last_message_ms = self.clock.ms()
        aid = msg["action_id"]
        failed = msg.get("result") in FAILED_RESULTS
        cur = self.actions.get(aid)
        if cur is not None:
            if msg["ts"] < cur["ts"] or msg == cur:
                return False, []
            self.actions[aid] = msg
            if aid in self._applied:
                return True, (self._revert(aid, msg["ts"]) if failed else [])
            if failed:
                return True, []
        else:
            self.actions[aid] = msg
            while len(self.actions) > MAX_ACTIONS:
                old_id, _ = self.actions.popitem(last=False)
                self._applied.discard(old_id)
            if failed:
                return True, []
        self._applied.add(aid)
        marks: list[TrustMark] = []
        undone_dev = self._undo(msg["undoes"], aid) if msg.get("undoes") else None
        dev_id = msg.get("device_id")
        if dev_id is None and msg.get("bed_id"):
            dev_id = device_for_bed(msg["bed_id"])
        dev = self.devices.get(dev_id) if dev_id else None
        if undone_dev is not None and (dev is None or undone_dev != dev.device_id):
            # The undo names the original action only: close (or reopen) that bed's trust interval.
            mark = self._sync_trust_interval(self.beds[self.devices[undone_dev].bed_id], msg["ts"])
            if mark is not None:
                marks.append(mark)
        if dev is None:
            return True, marks
        action = msg["action"]
        if action in ISOLATING_ACTIONS:
            dev.isolations[aid] = msg["ts"]
            self._iso_device[aid] = dev.device_id
            mark = self._mark_untrusted(self.beds[dev.bed_id], msg["ts"] - 1, msg["ts"])
            if mark is not None:
                marks.append(mark)
        elif action == "enable_client":
            self._enabled[aid] = (dev.device_id, dict(dev.isolations))
            dev.isolations.clear()
        interval_mark = self._sync_trust_interval(self.beds[dev.bed_id], msg["ts"])
        if interval_mark is not None and interval_mark not in marks:
            marks.append(interval_mark)
        return True, marks

    def _undo(self, original_id: str, undo_id: str) -> str | None:
        """Reverse an isolation or an enable_client; returns the affected device or None."""
        dev_id = self._iso_device.get(original_id)
        if dev_id is not None:
            ts = self.devices[dev_id].isolations.pop(original_id, None)
            if ts is not None:
                self._undone[undo_id] = ("isolation", original_id, dev_id, ts)
            return dev_id
        enabled = self._enabled.pop(original_id, None)
        if enabled is not None:  # undoing an enable_client puts its isolations back in force
            self.devices[enabled[0]].isolations.update(enabled[1])
            self._undone[undo_id] = ("enable", original_id, enabled[0], enabled[1])
            return enabled[0]
        return None

    def _revert(self, aid: str, ts: int) -> list[TrustMark]:
        """An action already applied was later reported failed: put the ward back as it was."""
        self._applied.discard(aid)
        devices: set[str] = set()
        dev_id = self._iso_device.get(aid)
        if dev_id is not None:
            self.devices[dev_id].isolations.pop(aid, None)
            devices.add(dev_id)
        enabled = self._enabled.pop(aid, None)
        if enabled is not None:
            self.devices[enabled[0]].isolations.update(enabled[1])
            devices.add(enabled[0])
        undone = self._undone.pop(aid, None)
        if undone is not None:
            kind, original_id, undone_dev, payload = undone
            dev = self.devices[undone_dev]
            if kind == "isolation":
                dev.isolations[original_id] = payload
            else:
                self._enabled[original_id] = (undone_dev, payload)
                for iso_id in payload:
                    dev.isolations.pop(iso_id, None)
            devices.add(undone_dev)
        marks = []
        for device_id in devices:
            mark = self._sync_trust_interval(self.beds[self.devices[device_id].bed_id], ts)
            if mark is not None:
                marks.append(mark)
        return marks

    def on_alert(self, msg: dict) -> bool:
        """Keep the latest state of each alert; returns True if this version is now the latest."""
        self.last_message_ms = self.clock.ms()
        aid = msg["alert_id"]
        cur = self.alerts.get(aid)
        if cur is not None and msg["ts"] < cur["ts"]:
            return False
        self.alerts[aid] = msg
        self.alerts.move_to_end(aid)
        while len(self.alerts) > MAX_ALERTS:
            self.alerts.popitem(last=False)
        return True

    def on_bedside(self, msg: dict) -> None:
        """Remember the newest bedside check per bed."""
        self.last_message_ms = self.clock.ms()
        bed = self.beds.get(msg["bed_id"])
        if bed is not None and (bed.last_bedside is None or msg["ts"] >= bed.last_bedside["ts"]):
            bed.last_bedside = msg

    def on_net(self, msg: dict) -> None:
        """Keep the newest and the last 30 min of network features per device."""
        self.last_message_ms = self.clock.ms()
        dev = self.devices.get(msg["device_id"])
        if dev is None:
            return
        dev.net_rows.append(msg)
        if dev.net is None or msg["window_start"] >= dev.net["window_start"]:
            dev.net = msg

    def on_record(self, msg: dict) -> dict | None:
        """Store a record message (same record_id replaces); returns the stored record or None if older."""
        self.last_message_ms = self.clock.ms()
        rid = msg["record_id"]
        cur = self.records.get(rid)
        # Agent publications remain authoritative; staff edits keep their separate audit rows.
        if cur is not None and msg["ts"] < cur["ts"]:
            return None
        rec = {"record_id": rid, "kind": msg["kind"], "ts": msg["ts"], "by": msg["by"],
               "version": cur["version"] + 1 if cur is not None else 1,
               "data": copy.deepcopy(msg["data"]), "updated_ts": None, "updated_by": None}
        self._put_record(rec)
        return rec

    def _put_record(self, rec: dict) -> None:
        self.records[rec["record_id"]] = rec
        self.records.move_to_end(rec["record_id"])
        while len(self.records) > MAX_RECORDS:
            self.records.popitem(last=False)

    # ------------------------------------------------------------------ staff changes

    def put_record(self, rec: dict) -> None:
        """Add a record created by staff (for example a ticket)."""
        self._put_record(rec)

    def patch_record(self, record_id: str, changes: dict[str, Any], by: str) -> tuple[dict, list[dict]]:
        """Apply staff edits to data fields; returns (record, audit rows). KeyError if unknown."""
        rec = self.records[record_id]
        now = self.clock.ms()
        data = copy.deepcopy(rec["data"])
        audits: list[dict] = []
        for k, new in changes.items():
            old = data.get(k)
            if k in data and old == new:
                continue
            audits.append({"record_id": record_id, "ts": now, "by": by, "field": k,
                           "old": copy.deepcopy(old), "new": copy.deepcopy(new), "bed_id": record_bed(rec)})
            data[k] = copy.deepcopy(new)
        if audits:
            rec = dict(rec, data=data, version=rec["version"] + 1, updated_ts=now, updated_by=by)
            self._put_record(rec)
        return rec, audits

    def add_manual(self, reading: dict) -> None:
        """Show a manual reading on its bed."""
        bed = self.beds[reading["bed_id"]]
        if bed.manual is None or reading["ts"] >= bed.manual["ts"]:
            bed.manual = reading

    def set_assignment(self, bed_id: str, assignment: dict) -> None:
        """Replace the bed's assignment {clinician_id, staff_id, status, ts, by}."""
        self.beds[bed_id].assignment = assignment

    def set_nurse_call(self, bed_id: str, call: dict | None) -> None:
        """Set (or clear) the bed's current nurse call."""
        self.beds[bed_id].nurse_call = call

    # ------------------------------------------------------------------ reads

    def bed_entry(self, bed_id: str) -> dict[str, Any]:
        """One bed as in GET /api/ward."""
        bed = self.beds[bed_id]
        v = self._view(bed)
        return {
            "bed_id": bed_id, "device_id": bed.cfg.device_id, "patient": bed.cfg.patient(),
            "nurse": bed.cfg.nurse, "latest": v.latest, "latest_trusted": v.latest_trusted,
            "display": v.display, "last_trusted_ts": v.last_trusted_ts, "offline_since": v.offline_since,
            "verdict": bed.verdict, "alarm_priority": bed.alarm.get("priority") if bed.alarm else None,
            "manual": bed.manual, "assignment": copy.deepcopy(bed.assignment), "nurse_call": bed.nurse_call,
        }

    def ward_body(self) -> dict[str, Any]:
        """The GET /api/ward body."""
        return {"ts": self.clock.ms(), "beds": [self.bed_entry(b) for b in self.beds]}

    def preview_body(self) -> dict[str, Any]:
        """The public landing-page body: no patient details, verdict reduced to name and priority."""
        beds = []
        for bed_id in self.ward.preview_beds:
            bed = self.beds[bed_id]
            v = self._view(bed)
            verdict = ({"verdict": bed.verdict["verdict"], "priority": bed.verdict["priority"],
                        "ts": bed.verdict["ts"]} if bed.verdict else None)
            beds.append({"bed_id": bed_id, "display": v.display, "latest": v.latest,
                         "latest_trusted": v.latest_trusted, "last_trusted_ts": v.last_trusted_ts,
                         "offline_since": v.offline_since, "verdict": verdict,
                         "alarm_priority": bed.alarm.get("priority") if bed.alarm else None})
        return {"ts": self.clock.ms(), "beds": beds}

    def device_brief(self, device_id: str) -> dict[str, Any]:
        """{online, isolated, isolated_since, last_seen_ts} for one device."""
        dev = self.devices[device_id]
        online = (dev.last_seen_mono is not None
                  and self.clock.mono() - dev.last_seen_mono <= OFFLINE_AFTER_S)
        iso = dev.isolated_since()
        return {"online": online, "isolated": iso is not None, "isolated_since": iso,
                "last_seen_ts": dev.last_seen_ms}

    def bed_detail(self, bed_id: str) -> dict[str, Any]:
        """One bed as in GET /api/beds/<id>."""
        bed = self.beds[bed_id]
        entry = self.bed_entry(bed_id)
        entry.update({
            "scores": dict(sorted(bed.scores.items())),
            "recent_verdicts": list(bed.recent_verdicts),
            "device": self.device_brief(bed.cfg.device_id),
            "open_alerts": self.open_alerts(bed_id),
            "last_bedside_check": bed.last_bedside,
        })
        return entry

    def history(self, bed_id: str, since_ms: int) -> list[dict]:
        """Per-second points of one bed since since_ms, oldest first (newest value wins within a second)."""
        pts = self.beds[bed_id].points
        start = bisect_right(pts, since_ms - 1, key=lambda p: p.ts)
        out: list[dict] = []
        last_sec = None
        for i in range(start, len(pts)):
            p = pts[i]
            sec = p.ts // 1000
            if sec == last_sec:
                out[-1] = p.history_point()
            else:
                out.append(p.history_point())
                last_sec = sec
        return out

    def buffer_start(self, bed_id: str) -> int | None:
        """ts of the oldest buffered point, or None."""
        pts = self.beds[bed_id].points
        return pts[0].ts if pts else None

    def open_alerts(self, bed_id: str | None = None) -> list[dict]:
        """Alerts not yet acknowledged or closed, newest first."""
        out = [a for a in self.alerts.values()
               if a["status"] in OPEN_ALERT_STATUSES and (bed_id is None or a["bed_id"] == bed_id)]
        out.sort(key=lambda a: a["ts"], reverse=True)
        return out

    def alert_to_ack(self, bed_id: str) -> dict | None:
        """The bed's open alert an acknowledge applies to: highest priority, then newest."""
        candidates = self.open_alerts(bed_id)
        if not candidates:
            return None
        return max(candidates, key=lambda a: (PRIORITY_RANK.get(a["priority"], 0), a["ts"]))

    def alerts_list(self, status: str | None = None) -> list[dict]:
        """Latest state of each alert, newest first, optionally filtered by status."""
        out = [a for a in self.alerts.values() if status is None or a["status"] == status]
        out.sort(key=lambda a: a["ts"], reverse=True)
        return out

    def actions_list(self, limit: int) -> list[dict]:
        """Newest actions first."""
        out = sorted(self.actions.values(), key=lambda a: a["ts"], reverse=True)
        return out[:limit]

    def devices_list(self) -> list[dict]:
        """GET /api/devices entries."""
        return [dict(device_id=d.device_id, bed_id=d.bed_id, **self.device_brief(d.device_id), net=d.net)
                for d in self.devices.values()]

    def net_rows(self, device_id: str, since_ms: int) -> list[dict]:
        """Buffered net_features rows of a device with window_start >= since_ms, oldest first."""
        return [r for r in self.devices[device_id].net_rows if r["window_start"] >= since_ms]

    def records_of(self, kind: str) -> list[dict]:
        """Records of one kind, newest first."""
        out = [r for r in self.records.values() if r["kind"] == kind]
        out.sort(key=lambda r: r["ts"], reverse=True)
        return out

    def newest_record(self, kind: str, since_ms: int | None = None) -> dict | None:
        """Newest record of a kind (with ts >= since_ms when given), or None."""
        best = None
        for r in self.records.values():
            if r["kind"] == kind and (since_ms is None or r["ts"] >= since_ms):
                if best is None or r["ts"] > best["ts"]:
                    best = r
        return best

    def beds_online(self) -> int:
        """Beds that are not offline."""
        return sum(1 for b in self.beds.values() if self._view(b).display != OFFLINE)

    # ------------------------------------------------------------------ warm start

    def warm_start(self, warm: "WarmStart") -> None:
        """Rebuild memory from the database after a restart."""
        now_ms, now_mono = self.clock.ms(), self.clock.mono()

        def mono_of(ms: int | None) -> float | None:
            return None if ms is None else now_mono - max(0.0, (now_ms - ms) / 1000.0)

        for msg in warm.actions:
            self.on_action(msg)
        for bed_id, msgs in warm.verdicts.items():
            bed = self.beds.get(bed_id)
            if bed is None or not msgs:
                continue
            for m in msgs:  # oldest first
                bed.recent_verdicts.appendleft(m)
            bed.verdict = msgs[-1]
        for bed_id, rows in warm.vitals.items():
            bed = self.beds.get(bed_id)
            if bed is None or not rows:
                continue
            bp = warm.last_bp.get(bed_id)
            for row in rows:
                p = point_from_row(row, bp)
                bp = p.bp
                bed.points.append(p)
            bed.last_point = bed.points[-1]
            bed.last_rx_ms = bed.last_point.received_ms
            bed.last_rx_mono = mono_of(bed.last_rx_ms)
            dev = self.devices[bed.cfg.device_id]
            dev.last_seen_ms, dev.last_seen_mono = bed.last_rx_ms, bed.last_rx_mono
            alarm_code = bed.last_point.alarm_code
            bed.alarm = ({"code": alarm_code, "priority": bed.last_point.alarm_priority}
                         if alarm_code else None)
        for msg in warm.scores:
            self.on_score(msg)
        for msg in warm.alerts:
            self.on_alert(msg)
        for msg in warm.bedside:
            self.on_bedside(msg)
        for device_id, msgs in warm.net.items():
            for msg in msgs:
                if device_id in self.devices:
                    self.on_net(msg)
        for rec in warm.records:
            self._put_record(rec)
        for reading in warm.manual:
            if reading["bed_id"] in self.beds:
                self.add_manual(reading)
        for a in warm.assignments:
            if a["bed_id"] in self.beds:
                self.set_assignment(a["bed_id"], {"clinician_id": a["clinician_id"], "staff_id": a["staff_id"],
                                                  "status": a["status"], "ts": a["ts"], "by": a["by"]})
        for call in warm.nurse_calls:
            if call["bed_id"] in self.beds and call["status"] == "open":
                self.set_nurse_call(call["bed_id"], call)
        self.last_message_ms = warm.last_message_ms
        for bed in self.beds.values():
            v = self._view(bed)
            bed.signature, bed.display = self._signature(bed, v), v.display


def record_bed(rec: dict) -> str | None:
    """data.bed_id of a record when it is a string, else None."""
    b = rec.get("data", {}).get("bed_id")
    return b if isinstance(b, str) else None


def record_device(rec: dict) -> str | None:
    """data.device_id of a record when it is a string, else None."""
    d = rec.get("data", {}).get("device_id")
    return d if isinstance(d, str) else None


def record_message(rec: dict) -> dict[str, Any]:
    """A record in ward/record message form, for /ws pushes of staff edits."""
    return {"v": 1, "type": "record", "ts": rec["updated_ts"] or rec["ts"], "kind": rec["kind"],
            "record_id": rec["record_id"], "by": rec["updated_by"] or rec["by"], "data": rec["data"],
            "version": rec["version"]}
