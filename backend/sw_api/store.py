"""Persistence interface, the in-memory store (SW_PG_DSN=memory) and the publication outbox.

The runtime calls every write method on the event loop and never waits for a database: the
memory store applies writes at once, the PostgreSQL store (postgres.py) queues them for the
one-second batch writer. Reads that RAM cannot answer are coroutines.
"""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol
from uuid import uuid4

from .state import Point, TrustMark, point_from_row


@dataclass
class WarmStart:
    """Run data loaded from the database after a restart (oldest first where it matters)."""

    actions: list = field(default_factory=list)
    verdicts: dict = field(default_factory=dict)
    vitals: dict = field(default_factory=dict)
    last_bp: dict = field(default_factory=dict)
    scores: list = field(default_factory=list)
    alerts: list = field(default_factory=list)
    bedside: list = field(default_factory=list)
    net: dict = field(default_factory=dict)
    records: list = field(default_factory=list)
    manual: list = field(default_factory=list)
    assignments: list = field(default_factory=list)
    nurse_calls: list = field(default_factory=list)
    last_message_ms: int | None = None
    reset_at: int | None = None


class Store(Protocol):
    """What the runtime needs from persistence; writes never block the event loop."""

    storage: str
    durable: bool
    sync_lookups: bool

    @property
    def db_ok(self) -> bool: ...
    async def start(self) -> WarmStart | None: ...
    async def close(self) -> None: ...
    def save(self, message: dict, point: Point | None = None, marks: list[TrustMark] = (),
             old_record: dict | None = None, record: dict | None = None) -> None: ...
    def save_record(self, record: dict, audits: list[dict]) -> None: ...
    def save_manual(self, reading: dict) -> None: ...
    def save_nurse_call(self, call: dict) -> None: ...
    def save_assignment(self, row: dict) -> None: ...
    def enqueue(self, message: dict) -> str: ...
    def pending_publications(self) -> list[tuple[str, dict]]: ...
    def published(self, publication_id: str) -> None: ...
    def trusted_point(self, bed_id: str, cutoff: int, inclusive: bool) -> Point | None: ...
    async def trusted_point_async(self, bed_id: str, cutoff: int, inclusive: bool) -> Point | None: ...
    async def history(self, bed_id: str, since_ms: int) -> list[dict]: ...
    async def net_rows(self, device_id: str, since_ms: int) -> list[dict]: ...
    async def untrusted_seconds(self, since_ms: int) -> dict[str, int]: ...
    def reset(self) -> None: ...


def vitals_row(message: dict, point: Point) -> dict[str, Any]:
    """The vitals_1s row for one accepted per-second point."""
    row = asdict(point)
    row["received_ts"] = row.pop("received_ms")
    row["bed_id"], row["device_id"] = message["bed_id"], message["device_id"]
    return row


def history_point(row: dict) -> dict[str, Any]:
    """A vitals_1s row as one point of /api/beds/<id>/history."""
    return {k: row.get(k) for k in ("ts", "hr", "spo2", "rr", "sys", "dia", "map", "abp_mean", "verdict")} | {
        "trusted": bool(row.get("trusted"))}


class MemoryStore:
    """Keeps scalars and original event payloads in RAM; never stores raw waveforms. Not durable."""

    storage = "memory"
    durable = False
    sync_lookups = True

    def __init__(self) -> None:
        self.demo_runs: list[dict] = []
        self.outbox: dict[str, dict] = {}
        self.reset()

    @property
    def db_ok(self) -> bool:
        """There is no database in memory mode."""
        return False

    async def start(self) -> WarmStart | None:
        """Nothing to load: memory mode always starts empty."""
        return None

    async def close(self) -> None:
        """Nothing to flush."""

    def reset(self) -> None:
        """Forget run data; demo_runs stay. Queued publications of the old run are discarded."""
        self.vitals: dict[tuple[str, int], dict] = {}
        self.scores: dict[tuple[str, str, int], dict] = {}
        self.verdicts: dict[tuple[str, int], dict] = {}
        self.actions: dict[str, dict] = {}
        self.alerts: dict[str, dict] = {}
        self.alert_history: list[dict] = []
        self.records: dict[str, dict] = {}
        self.record_audit: list[dict] = []
        self.bedside: dict[tuple, dict] = {}
        self.net: dict[tuple, dict] = {}
        self.requests: dict[str, dict] = {}
        self.manual: list[dict] = []
        self.nurse_calls: dict[str, dict] = {}
        self.assignments: list[dict] = []
        self.outbox.clear()

    # ------------------------------------------------------------------ writes

    def save(self, message: dict, point: Point | None = None, marks: list[TrustMark] = (),
             old_record: dict | None = None, record: dict | None = None) -> None:
        """Store one hub message (incoming or published by us) and apply trust marks."""
        m = copy.deepcopy(message)
        kind = m["type"]
        if kind == "vitals" and point is not None:
            row = vitals_row(m, point)
            key = (m["bed_id"], point.ts // 1000)
            if key not in self.vitals or row["ts"] >= self.vitals[key]["ts"]:
                self.vitals[key] = row
        elif kind == "score":
            self.scores[(m["bed_id"], m["model"], m["window_start"])] = m
        elif kind == "verdict":
            self.verdicts[(m["bed_id"], m["ts"])] = m
        elif kind == "action":
            cur = self.actions.get(m["action_id"])
            if cur is None or m["ts"] >= cur["ts"]:
                self.actions[m["action_id"]] = m
        elif kind == "alert":
            if m not in self.alert_history:
                self.alert_history.append(m)
            cur = self.alerts.get(m["alert_id"])
            if cur is None or m["ts"] >= cur["ts"]:
                self.alerts[m["alert_id"]] = m
        elif kind == "record" and record is not None:
            if old_record is not None:
                self.record_audit.append({"record_id": m["record_id"], "ts": m["ts"], "by": m["by"],
                                          "field": "*", "old": copy.deepcopy(old_record),
                                          "new": copy.deepcopy(record)})
            self.records[m["record_id"]] = copy.deepcopy(record)
        elif kind == "bedside_check":
            self.bedside[(m["bed_id"], m["ts"], m["by"], m["result"])] = m
        elif kind == "net_features":
            self.net[(m["device_id"], m["window_start"])] = m
        elif kind == "request":
            self.requests[m["request_id"]] = m
        elif kind == "demo_control":
            self.demo_runs.append(m)
        for mark in marks:
            for (bed_id, _), row in self.vitals.items():
                if bed_id == mark.bed_id and mark.after_ts < row["ts"] <= mark.upto_ts:
                    row["trusted"] = False

    def save_record(self, record: dict, audits: list[dict]) -> None:
        """Store a record created or edited by staff, with its field-level audit rows."""
        self.records[record["record_id"]] = copy.deepcopy(record)
        self.record_audit.extend(copy.deepcopy(audits))

    def save_manual(self, reading: dict) -> None:
        """Store a manual reading (kept apart from monitor values)."""
        self.manual.append(copy.deepcopy(reading))

    def save_nurse_call(self, call: dict) -> None:
        """Store (or update) a nurse call."""
        self.nurse_calls[call["call_id"]] = copy.deepcopy(call)

    def save_assignment(self, row: dict) -> None:
        """Append an assignment change."""
        self.assignments.append(copy.deepcopy(row))

    # ------------------------------------------------------------------ outbox

    def enqueue(self, message: dict) -> str:
        """Queue a publication; it stays queued until the hub accepts it."""
        publication_id = uuid4().hex
        self.outbox[publication_id] = copy.deepcopy(message)
        return publication_id

    def pending_publications(self) -> list[tuple[str, dict]]:
        """Unsent publications, oldest first."""
        return [(key, copy.deepcopy(value)) for key, value in self.outbox.items()]

    def published(self, publication_id: str) -> None:
        """The hub accepted this publication."""
        self.outbox.pop(publication_id, None)

    # ------------------------------------------------------------------ reads

    def trusted_point(self, bed_id: str, cutoff: int, inclusive: bool) -> Point | None:
        """Newest trusted per-second point at (or strictly before) cutoff."""
        rows = [r for (b, _), r in self.vitals.items() if b == bed_id and r["trusted"]
                and (r["ts"] <= cutoff if inclusive else r["ts"] < cutoff)]
        if not rows:
            return None
        row = max(rows, key=lambda r: r["ts"])
        return point_from_row(row, row.get("bp"))

    async def trusted_point_async(self, bed_id: str, cutoff: int, inclusive: bool) -> Point | None:
        """Same as trusted_point (memory answers at once)."""
        return self.trusted_point(bed_id, cutoff, inclusive)

    async def history(self, bed_id: str, since_ms: int) -> list[dict]:
        """Stored per-second points of a bed with ts >= since_ms, oldest first."""
        rows = sorted((r for (b, _), r in self.vitals.items() if b == bed_id and r["ts"] >= since_ms),
                      key=lambda r: r["ts"])
        return [history_point(r) for r in rows]

    async def net_rows(self, device_id: str, since_ms: int) -> list[dict]:
        """Stored net_features messages with window_start >= since_ms, oldest first."""
        rows = [m for (d, ws), m in self.net.items() if d == device_id and ws >= since_ms]
        return copy.deepcopy(sorted(rows, key=lambda m: m["window_start"]))

    async def untrusted_seconds(self, since_ms: int) -> dict[str, int]:
        """Per bed, how many stored seconds since since_ms were not trusted."""
        out: dict[str, int] = {}
        for (bed_id, _), row in self.vitals.items():
            if row["ts"] >= since_ms and not row["trusted"]:
                out[bed_id] = out.get(bed_id, 0) + 1
        return out
