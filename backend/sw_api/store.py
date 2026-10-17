"""Phase A in-memory persistence and publication outbox (not durable across restart)."""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from typing import Protocol
from uuid import uuid4

from .state import Point, TrustMark, point_from_row


@dataclass
class WarmStart:
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


class Store(Protocol):
    """Nonblocking memory operations used by the Phase A runtime."""
    def save(self, message: dict, point: Point | None = None, marks: list[TrustMark] = (), old_record: dict | None = None, record: dict | None = None) -> None: ...
    def enqueue(self, message: dict) -> str: ...
    def pending_publications(self) -> list[tuple[str, dict]]: ...
    def published(self, publication_id: str) -> None: ...
    def trusted_point(self, bed_id: str, cutoff: int, inclusive: bool) -> Point | None: ...
    def reset(self) -> None: ...


class MemoryStore:
    """Keep scalars and original event payloads; never persist raw waveforms."""

    def __init__(self) -> None:
        self.demo_runs: list[dict] = []
        self.outbox: dict[str, dict] = {}
        self.reset()

    def reset(self) -> None:
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
        # Discard queued run work; the reset control is enqueued after this barrier.
        self.outbox.clear()

    def save(self, message: dict, point: Point | None = None, marks: list[TrustMark] = (), old_record: dict | None = None, record: dict | None = None) -> None:
        m = copy.deepcopy(message)
        kind = m["type"]
        if kind == "vitals" and point is not None:
            row = asdict(point)
            row["received_ts"] = row.pop("received_ms")
            key = (m["bed_id"], m["ts"] // 1000)
            if key not in self.vitals or row["ts"] >= self.vitals[key]["ts"]:
                self.vitals[key] = row
        elif kind == "score":
            self.scores[(m["bed_id"], m["model"], m["window_start"])] = m
        elif kind == "verdict":
            self.verdicts[(m["bed_id"], m["ts"])] = m
        elif kind == "action":
            self.actions.setdefault(m["action_id"], m)
        elif kind == "alert":
            if m not in self.alert_history:
                self.alert_history.append(m)
            cur = self.alerts.get(m["alert_id"])
            if cur is None or m["ts"] >= cur["ts"]:
                self.alerts[m["alert_id"]] = m
        elif kind == "record" and record is not None:
            if old_record is not None:
                self.record_audit.append({"record_id": m["record_id"], "ts": m["ts"], "by": m["by"], "old": copy.deepcopy(old_record), "new": copy.deepcopy(record)})
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

    def enqueue(self, message: dict) -> str:
        publication_id = uuid4().hex
        self.outbox[publication_id] = copy.deepcopy(message)
        return publication_id

    def pending_publications(self) -> list[tuple[str, dict]]:
        return [(key, copy.deepcopy(value)) for key, value in self.outbox.items()]

    def published(self, publication_id: str) -> None:
        self.outbox.pop(publication_id, None)

    def trusted_point(self, bed_id: str, cutoff: int, inclusive: bool) -> Point | None:
        rows = [r for (b, _), r in self.vitals.items() if b == bed_id and r["trusted"] and (r["ts"] <= cutoff if inclusive else r["ts"] < cutoff)]
        if not rows:
            return None
        row = max(rows, key=lambda r: r["ts"])
        return point_from_row(row, row.get("bp"))
