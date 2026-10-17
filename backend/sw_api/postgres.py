"""PostgreSQL store (psycopg 3, pure-Python mode with the system libpq).

Writes go through the one-second BatchWriter; nothing on the request or MQTT path waits for SQL.
Reads that the 30-minute RAM buffers cannot answer (older history, trusted pins older than the
buffer, blind time) use a separate autocommit connection. schema.sql runs at every start-up.
"""
from __future__ import annotations

import asyncio
import copy
import logging
from pathlib import Path
from typing import Any

from .config import WardConfig
from .state import BUFFER_S, NET_BUFFER, Point, TrustMark, point_from_row
from .store import MemoryStore, WarmStart, history_point, vitals_row
from .writer import BatchWriter

LOG = logging.getLogger(__name__)

WARM_ACTIONS = 5000
WARM_ALERTS = 10000
WARM_RECORDS = 10000
CONNECT_ATTEMPTS = 10

# Tables holding one demo run's data; /api/demo/reset empties them (beds, patients, demo_runs stay).
RUN_TABLES = ("vitals_1s", "scores", "verdicts", "actions", "alerts", "alert_history", "bedside_checks",
              "manual_readings", "net_features", "records", "record_audit", "requests", "nurse_calls",
              "assignments", "outbox")

_VITALS_COLS = ("bed_id", "ts", "second", "device_id", "seq", "hr", "spo2", "rr", "sys", "dia", "map",
                "nibp_ts", "abp_mean", "alarm_code", "alarm_priority", "verdict", "trusted", "received_ts")
SQL_VITALS = (
    f"INSERT INTO vitals_1s ({', '.join(_VITALS_COLS)}) VALUES ({', '.join('%s' for _ in _VITALS_COLS)}) "
    "ON CONFLICT (bed_id, second) DO UPDATE SET "
    + ", ".join(f"{c} = EXCLUDED.{c}" for c in _VITALS_COLS if c not in ("bed_id", "second"))
    + " WHERE vitals_1s.ts <= EXCLUDED.ts")
SQL_MARK = "UPDATE vitals_1s SET trusted = false WHERE bed_id = %s AND ts > %s AND ts <= %s AND trusted"
SQL_SCORE = (
    "INSERT INTO scores (bed_id, ts, model, model_version, window_s, score, label, reason, extra, received_ts) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (bed_id, model, ts) DO UPDATE SET "
    "model_version = EXCLUDED.model_version, window_s = EXCLUDED.window_s, score = EXCLUDED.score, "
    "label = EXCLUDED.label, reason = EXCLUDED.reason, extra = EXCLUDED.extra, received_ts = EXCLUDED.received_ts")
SQL_VERDICT = (
    "INSERT INTO verdicts (bed_id, ts, window_start, verdict, priority, confidence, trust, last_trusted_ts, msg) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (bed_id, ts) DO NOTHING")
SQL_ACTION = (
    "INSERT INTO actions (action_id, ts, actor, action, bed_id, device_id, detail, undo_id, undoes, approved_by, "
    "result, msg) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (action_id) DO UPDATE SET "
    "ts = EXCLUDED.ts, actor = EXCLUDED.actor, action = EXCLUDED.action, bed_id = EXCLUDED.bed_id, "
    "device_id = EXCLUDED.device_id, detail = EXCLUDED.detail, undo_id = EXCLUDED.undo_id, "
    "undoes = EXCLUDED.undoes, approved_by = EXCLUDED.approved_by, result = EXCLUDED.result, msg = EXCLUDED.msg "
    "WHERE actions.ts <= EXCLUDED.ts")
SQL_ALERT = (
    "INSERT INTO alerts (alert_id, ts, bed_id, verdict, priority, status, ladder_step, acked_by, acked_ts, msg) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (alert_id) DO UPDATE SET ts = EXCLUDED.ts, "
    "bed_id = EXCLUDED.bed_id, verdict = EXCLUDED.verdict, priority = EXCLUDED.priority, status = EXCLUDED.status, "
    "ladder_step = EXCLUDED.ladder_step, acked_by = EXCLUDED.acked_by, acked_ts = EXCLUDED.acked_ts, "
    "msg = EXCLUDED.msg WHERE alerts.ts <= EXCLUDED.ts")
SQL_ALERT_HISTORY = (
    "INSERT INTO alert_history (alert_id, ts, bed_id, status, ladder_step, msg, received_ts) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (alert_id, ts, status, ladder_step) DO NOTHING")
SQL_BEDSIDE = ("INSERT INTO bedside_checks (bed_id, ts, result, actor) VALUES (%s, %s, %s, %s) "
               "ON CONFLICT (bed_id, ts, actor, result) DO NOTHING")
SQL_NET = (
    "INSERT INTO net_features (device_id, ts, window_s, data, received_ts, msgs_per_s, bytes_per_s, malformed, "
    "seq_gaps, seq_repeats, stale_ms) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
    "ON CONFLICT (device_id, ts) DO UPDATE SET window_s = EXCLUDED.window_s, data = EXCLUDED.data, "
    "received_ts = EXCLUDED.received_ts, msgs_per_s = EXCLUDED.msgs_per_s, bytes_per_s = EXCLUDED.bytes_per_s, "
    "malformed = EXCLUDED.malformed, seq_gaps = EXCLUDED.seq_gaps, seq_repeats = EXCLUDED.seq_repeats, "
    "stale_ms = EXCLUDED.stale_ms")
SQL_RECORD = (
    "INSERT INTO records (record_id, kind, ts, actor, version, data, bed_id, device_id, updated_ts, updated_by) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (record_id) DO UPDATE SET kind = EXCLUDED.kind, "
    "ts = EXCLUDED.ts, actor = EXCLUDED.actor, version = EXCLUDED.version, data = EXCLUDED.data, "
    "bed_id = EXCLUDED.bed_id, device_id = EXCLUDED.device_id, updated_ts = EXCLUDED.updated_ts, "
    "updated_by = EXCLUDED.updated_by WHERE records.version <= EXCLUDED.version")
SQL_AUDIT = ("INSERT INTO record_audit (record_id, ts, actor, field, old_value, new_value, bed_id) "
             "VALUES (%s, %s, %s, %s, %s, %s, %s)")
SQL_REQUEST = ("INSERT INTO requests (request_id, ts, actor, action, target_id, bed_id, note, msg) "
               "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (request_id) DO NOTHING")
SQL_DEMO = ("INSERT INTO demo_runs (run_id, cmd, ts, start_at_s, scenario, speed, actor) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (run_id, cmd) DO UPDATE SET ts = EXCLUDED.ts, "
            "start_at_s = EXCLUDED.start_at_s, scenario = EXCLUDED.scenario, speed = EXCLUDED.speed, "
            "actor = EXCLUDED.actor")
SQL_MANUAL = ("INSERT INTO manual_readings (reading_id, bed_id, ts, actor, hr, spo2, sys, dia, rr, notes) "
              "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (reading_id) DO NOTHING")
SQL_CALL = ("INSERT INTO nurse_calls (call_id, bed_id, ts, actor, note, urgency, status, closed_ts, closed_by) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (call_id) DO UPDATE SET "
            "status = EXCLUDED.status, closed_ts = EXCLUDED.closed_ts, closed_by = EXCLUDED.closed_by")
SQL_ASSIGNMENT = ("INSERT INTO assignments (bed_id, ts, nurse, clinician_id, status, actor) "
                  "VALUES (%s, %s, %s, %s, %s, %s)")
SQL_OUTBOX = ("INSERT INTO outbox (publication_id, ts, msg) VALUES (%s, %s, %s) "
              "ON CONFLICT (publication_id) DO NOTHING")
SQL_SENT = "UPDATE outbox SET sent_ts = %s WHERE publication_id = %s"
SQL_RESET = {t: f"DELETE FROM {t} WHERE %s::int IS NOT NULL" for t in RUN_TABLES}
_RESET_SQL = frozenset(SQL_RESET.values())


def _jsonb(value: Any) -> Any:
    from psycopg.types.json import Jsonb
    return Jsonb(value)


class PostgresStore(MemoryStore):
    """MemoryStore for the small lookup tables (actions, alerts, records, requests, outbox) plus
    durable batched writes of everything to PostgreSQL. Bulky series stay only in the database."""

    storage = "postgresql"
    durable = True
    sync_lookups = False

    def __init__(self, dsn: str, ward: WardConfig, schema_sql: Path, clock: Any,
                 interval_s: float = 1.0) -> None:
        self.dsn, self.ward, self.schema_sql, self.clock = dsn, ward, schema_sql, clock
        self.writer = BatchWriter(self._connect, interval_s)
        self._read: Any = None
        self._read_lock = asyncio.Lock()
        self._read_ok = False
        self._initialised = False
        super().__init__()
        self._initialised = True

    # ------------------------------------------------------------------ connections

    async def _connect(self, autocommit: bool = False) -> Any:
        import psycopg
        return await psycopg.AsyncConnection.connect(self.dsn, autocommit=autocommit, connect_timeout=5)

    @property
    def db_ok(self) -> bool:
        """The last batch committed (or nothing failed yet) and the read connection works."""
        return self._read_ok and (self.writer.ok or (self.writer.last_error is None))

    async def _reader(self) -> Any:
        if self._read is None or self._read.closed:
            self._read = await self._connect(autocommit=True)
        return self._read

    async def _query(self, sql: str, params: Any = ()) -> list[dict]:
        from psycopg.rows import dict_row
        async with self._read_lock:
            try:
                conn = await self._reader()
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(sql, params)
                    rows = await cur.fetchall() if cur.description else []
                self._read_ok = True
                return rows
            except Exception:
                self._read_ok = False
                if self._read is not None:
                    try:
                        await self._read.close()
                    except Exception:  # noqa: BLE001
                        pass
                    self._read = None
                raise

    async def start(self) -> WarmStart:
        """Connect (with retries), apply schema.sql, sync ward.yaml, start the writer, load warm state."""
        delay = 0.5
        for attempt in range(1, CONNECT_ATTEMPTS + 1):
            try:
                conn = await self._connect(autocommit=True)
                break
            except Exception as exc:  # noqa: BLE001
                if attempt == CONNECT_ATTEMPTS:
                    raise
                LOG.warning("PostgreSQL not reachable (attempt %d): %s", attempt, exc)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 5.0)
        try:
            await conn.execute(self.schema_sql.read_text(encoding="utf-8"))
            now = self.clock.ms()
            async with conn.transaction():
                for b in self.ward.beds:
                    await conn.execute(
                        "INSERT INTO beds (bed_id, device_id, nurse, ts) VALUES (%s, %s, %s, %s) "
                        "ON CONFLICT (bed_id) DO UPDATE SET device_id = EXCLUDED.device_id, "
                        "nurse = EXCLUDED.nurse, ts = EXCLUDED.ts", (b.bed_id, b.device_id, b.nurse, now))
                    await conn.execute(
                        "INSERT INTO patients (bed_id, initials, age, sex, ts) VALUES (%s, %s, %s, %s, %s) "
                        "ON CONFLICT (bed_id) DO UPDATE SET initials = EXCLUDED.initials, age = EXCLUDED.age, "
                        "sex = EXCLUDED.sex, ts = EXCLUDED.ts", (b.bed_id, b.initials, b.age, b.sex, now))
        finally:
            await conn.close()
        self._read_ok = True
        warm = await self.load()
        self.writer.start()
        return warm

    async def close(self) -> None:
        """Drain the batch writer, then close both connections."""
        await self.writer.close()
        if self._read is not None:
            await self._read.close()
            self._read = None

    # ------------------------------------------------------------------ warm start

    async def load(self) -> WarmStart:
        """Rebuild what RAM needs from the database (the newest 30 minutes per bed)."""
        q = self._query
        w = WarmStart()
        window = BUFFER_S * 1000
        w.actions = [r["msg"] for r in reversed(await q(
            "SELECT msg FROM actions ORDER BY ts DESC LIMIT %s", (WARM_ACTIONS,)))]
        for r in await q("SELECT bed_id, msg FROM (SELECT bed_id, ts, msg, row_number() OVER "
                         "(PARTITION BY bed_id ORDER BY ts DESC) AS rn FROM verdicts) v WHERE rn <= 10 "
                         "ORDER BY bed_id, ts"):
            w.verdicts.setdefault(r["bed_id"], []).append(r["msg"])
        for r in await q("WITH m AS (SELECT bed_id, max(ts) AS mx FROM vitals_1s GROUP BY bed_id) "
                         "SELECT v.* FROM vitals_1s v JOIN m USING (bed_id) WHERE v.ts > m.mx - %s "
                         "ORDER BY v.bed_id, v.ts", (window,)):
            w.vitals.setdefault(r["bed_id"], []).append(dict(r))
        for r in await q("WITH m AS (SELECT bed_id, max(ts) AS mx FROM vitals_1s GROUP BY bed_id) "
                         "SELECT DISTINCT ON (v.bed_id) v.bed_id, v.sys, v.dia, v.map, v.nibp_ts FROM vitals_1s v "
                         "JOIN m USING (bed_id) WHERE v.nibp_ts IS NOT NULL AND v.ts <= m.mx - %s "
                         "ORDER BY v.bed_id, v.ts DESC", (window,)):
            w.last_bp[r["bed_id"]] = {"sys": r["sys"], "dia": r["dia"], "map": r["map"], "ts": r["nibp_ts"]}
        for r in await q("SELECT DISTINCT ON (bed_id, model) * FROM scores ORDER BY bed_id, model, ts DESC"):
            w.scores.append({"v": 1, "type": "score", "bed_id": r["bed_id"], "model": r["model"],
                             "model_version": r["model_version"], "window_start": r["ts"],
                             "window_s": r["window_s"], "score": r["score"], "label": r["label"],
                             "reason": r["reason"], "extra": r["extra"]})
        w.alerts = [r["msg"] for r in reversed(await q(
            "SELECT msg FROM alerts ORDER BY ts DESC LIMIT %s", (WARM_ALERTS,)))]
        for r in await q("SELECT DISTINCT ON (bed_id) * FROM bedside_checks ORDER BY bed_id, ts DESC"):
            w.bedside.append({"v": 1, "type": "bedside_check", "bed_id": r["bed_id"], "ts": r["ts"],
                              "result": r["result"], "by": r["actor"]})
        for r in await q("SELECT device_id, data FROM (SELECT device_id, ts, data, row_number() OVER "
                         "(PARTITION BY device_id ORDER BY ts DESC) AS rn FROM net_features) n "
                         "WHERE rn <= %s ORDER BY device_id, ts", (NET_BUFFER,)):
            w.net.setdefault(r["device_id"], []).append(r["data"])
        for r in reversed(await q("SELECT * FROM records ORDER BY ts DESC LIMIT %s", (WARM_RECORDS,))):
            w.records.append({"record_id": r["record_id"], "kind": r["kind"], "ts": r["ts"], "by": r["actor"],
                              "version": r["version"], "data": r["data"], "updated_ts": r["updated_ts"],
                              "updated_by": r["updated_by"]})
        for r in await q("SELECT DISTINCT ON (bed_id) * FROM manual_readings ORDER BY bed_id, ts DESC"):
            w.manual.append({"reading_id": r["reading_id"], "bed_id": r["bed_id"], "ts": r["ts"], "by": r["actor"],
                             "hr": r["hr"], "spo2": r["spo2"], "sys": r["sys"], "dia": r["dia"], "rr": r["rr"],
                             "notes": r["notes"]})
        for r in await q("SELECT DISTINCT ON (bed_id) * FROM assignments ORDER BY bed_id, ts DESC"):
            w.assignments.append({"bed_id": r["bed_id"], "clinician_id": r["clinician_id"], "staff_id": r["nurse"],
                                  "status": r["status"], "ts": r["ts"], "by": r["actor"]})
        for r in await q("SELECT * FROM nurse_calls WHERE status = 'open' ORDER BY ts"):
            w.nurse_calls.append({"call_id": r["call_id"], "bed_id": r["bed_id"], "ts": r["ts"], "by": r["actor"],
                                  "note": r["note"], "urgency": r["urgency"], "status": r["status"]})
        rows = await q("SELECT max(received_ts) AS last FROM vitals_1s")
        w.last_message_ms = rows[0]["last"] if rows else None
        rows = await q("SELECT max(ts) AS reset_at FROM demo_runs WHERE cmd = 'reset'")
        w.reset_at = rows[0]["reset_at"] if rows else None
        # RAM lookup tables and the unsent outbox.
        for m in w.actions:
            self.actions[m["action_id"]] = m
        for m in w.alerts:
            self.alerts[m["alert_id"]] = m
        for rec in w.records:
            self.records[rec["record_id"]] = rec
        for r in await q("SELECT publication_id, msg FROM outbox WHERE sent_ts IS NULL ORDER BY seq"):
            self.outbox[r["publication_id"]] = r["msg"]
        return w

    # ------------------------------------------------------------------ writes

    def reset(self) -> None:
        """Forget run data in RAM, drop queued run rows, and queue the deletes (demo_runs stay)."""
        super().reset()
        if not self._initialised:  # called from MemoryStore.__init__
            return
        writer = self.writer
        writer.discard(lambda sql: sql == SQL_DEMO or sql in _RESET_SQL)
        for table in RUN_TABLES:
            writer.put(SQL_RESET[table], (1,))

    def save(self, message: dict, point: Point | None = None, marks: list[TrustMark] = (),
             old_record: dict | None = None, record: dict | None = None) -> None:
        """Queue the rows for one hub message; keep only the small lookup tables in RAM."""
        m = message
        kind = m["type"]
        put = self.writer.put
        now = self.clock.ms()
        if kind == "vitals" and point is not None:
            row = vitals_row(m, point)
            row["second"] = point.ts // 1000
            put(SQL_VITALS, tuple(row[c] for c in _VITALS_COLS))
        elif kind == "score":
            put(SQL_SCORE, (m["bed_id"], m["window_start"], m["model"], m["model_version"], m["window_s"],
                            m["score"], m["label"], m["reason"], _jsonb(m["extra"]), now))
        elif kind == "verdict":
            put(SQL_VERDICT, (m["bed_id"], m["ts"], m["window_start"], m["verdict"], m["priority"],
                              m["confidence"], m["trust"], m["last_trusted_ts"], _jsonb(m)))
        elif kind == "action":
            put(SQL_ACTION, (m["action_id"], m["ts"], m["by"], m["action"], m["bed_id"], m["device_id"],
                             m["detail"], m["undo_id"], m["undoes"], m["approved_by"], m["result"], _jsonb(m)))
            cur = self.actions.get(m["action_id"])
            if cur is None or m["ts"] >= cur["ts"]:
                self.actions[m["action_id"]] = copy.deepcopy(m)
        elif kind == "alert":
            put(SQL_ALERT, (m["alert_id"], m["ts"], m["bed_id"], m["verdict"], m["priority"], m["status"],
                            m["ladder_step"], m["acked_by"], m["acked_ts"], _jsonb(m)))
            put(SQL_ALERT_HISTORY, (m["alert_id"], m["ts"], m["bed_id"], m["status"], m["ladder_step"],
                                    _jsonb(m), now))
            cur = self.alerts.get(m["alert_id"])
            if cur is None or m["ts"] >= cur["ts"]:
                self.alerts[m["alert_id"]] = copy.deepcopy(m)
        elif kind == "record" and record is not None:
            if old_record is not None:
                put(SQL_AUDIT, (m["record_id"], m["ts"], m["by"], "*", _jsonb(old_record), _jsonb(record),
                                _bed_of(record)))
            self._put_record(record)
        elif kind == "bedside_check":
            put(SQL_BEDSIDE, (m["bed_id"], m["ts"], m["result"], m["by"]))
        elif kind == "net_features":
            put(SQL_NET, (m["device_id"], m["window_start"], m["window_s"], _jsonb(m), now, m.get("msgs_per_s"),
                          m.get("bytes_per_s"), m.get("malformed"), m.get("seq_gaps"), m.get("seq_repeats"),
                          m.get("stale_ms")))
        elif kind == "request":
            put(SQL_REQUEST, (m["request_id"], m["ts"], m["by"], m["action"], m["target_id"], m["bed_id"],
                              m["note"], _jsonb(m)))
            self.requests[m["request_id"]] = copy.deepcopy(m)
        elif kind == "demo_control":
            put(SQL_DEMO, (m["run_id"], m["cmd"], m["ts"], m["start_at_s"], m.get("scenario"), m.get("speed"),
                           m.get("by")))
            self.demo_runs.append(copy.deepcopy(m))
        for mark in marks:
            put(SQL_MARK, (mark.bed_id, mark.after_ts, mark.upto_ts))

    def _put_record(self, record: dict) -> None:
        self.records[record["record_id"]] = copy.deepcopy(record)
        self.writer.put(SQL_RECORD, (record["record_id"], record["kind"], record["ts"], record["by"],
                                     record["version"], _jsonb(record["data"]), _bed_of(record),
                                     _device_of(record), record.get("updated_ts"), record.get("updated_by")))

    def save_record(self, record: dict, audits: list[dict]) -> None:
        """Queue a staff-created or staff-edited record and its audit rows."""
        self._put_record(record)
        for a in audits:
            self.writer.put(SQL_AUDIT, (a["record_id"], a["ts"], a["by"], a["field"], _jsonb(a["old"]),
                                        _jsonb(a["new"]), a.get("bed_id")))

    def save_manual(self, reading: dict) -> None:
        """Queue a manual reading."""
        r = reading
        self.writer.put(SQL_MANUAL, (r["reading_id"], r["bed_id"], r["ts"], r["by"], r["hr"], r["spo2"], r["sys"],
                                     r["dia"], r["rr"], r["notes"]))

    def save_nurse_call(self, call: dict) -> None:
        """Queue a nurse call (insert or status update)."""
        c = call
        self.writer.put(SQL_CALL, (c["call_id"], c["bed_id"], c["ts"], c["by"], c["note"], c["urgency"],
                                   c["status"], c.get("closed_ts"), c.get("closed_by")))

    def save_assignment(self, row: dict) -> None:
        """Queue an assignment change."""
        self.writer.put(SQL_ASSIGNMENT, (row["bed_id"], row["ts"], row["staff_id"], row["clinician_id"],
                                         row["status"], row["by"]))

    def enqueue(self, message: dict) -> str:
        """Queue a publication in RAM and durably (the outbox row commits with the next batch)."""
        publication_id = super().enqueue(message)
        self.writer.put(SQL_OUTBOX, (publication_id, self.clock.ms(), _jsonb(message)))
        return publication_id

    def published(self, publication_id: str) -> None:
        """Mark a publication sent (also in the database)."""
        if publication_id in self.outbox:
            super().published(publication_id)
            self.writer.put(SQL_SENT, (self.clock.ms(), publication_id))

    # ------------------------------------------------------------------ reads

    def trusted_point(self, bed_id: str, cutoff: int, inclusive: bool) -> Point | None:
        """Not available synchronously in PostgreSQL mode; use trusted_point_async."""
        raise RuntimeError("PostgresStore lookups are asynchronous")

    async def trusted_point_async(self, bed_id: str, cutoff: int, inclusive: bool) -> Point | None:
        """Newest trusted stored second at (or strictly before) cutoff, with its cuff reading."""
        op = "<=" if inclusive else "<"
        await self.writer.flush()  # rows of the last second must be visible
        rows = await self._query(f"SELECT * FROM vitals_1s WHERE bed_id = %s AND trusted AND ts {op} %s "
                                 "ORDER BY ts DESC LIMIT 1", (bed_id, cutoff))
        if not rows:
            return None
        row = dict(rows[0])
        bp = None
        if row.get("nibp_ts") is None:
            prev = await self._query("SELECT sys, dia, map, nibp_ts FROM vitals_1s WHERE bed_id = %s AND "
                                     "nibp_ts IS NOT NULL AND ts < %s ORDER BY ts DESC LIMIT 1", (bed_id, row["ts"]))
            if prev:
                p = prev[0]
                bp = {"sys": p["sys"], "dia": p["dia"], "map": p["map"], "ts": p["nibp_ts"]}
        return point_from_row(row, bp)

    async def history(self, bed_id: str, since_ms: int) -> list[dict]:
        """Stored per-second points with ts >= since_ms, oldest first (uses vitals_1s_bed_ts)."""
        rows = await self._query("SELECT ts, hr, spo2, rr, sys, dia, map, abp_mean, verdict, trusted FROM vitals_1s "
                                 "WHERE bed_id = %s AND ts >= %s ORDER BY ts", (bed_id, since_ms))
        return [history_point(r) for r in rows]

    async def net_rows(self, device_id: str, since_ms: int) -> list[dict]:
        """Stored net_features messages with window_start >= since_ms, oldest first."""
        rows = await self._query("SELECT data FROM net_features WHERE device_id = %s AND ts >= %s ORDER BY ts",
                                 (device_id, since_ms))
        return [r["data"] for r in rows]

    async def untrusted_seconds(self, since_ms: int) -> dict[str, int]:
        """Per bed, stored seconds since since_ms that were not trusted."""
        rows = await self._query("SELECT bed_id, count(*) AS n FROM vitals_1s WHERE ts >= %s AND NOT trusted "
                                 "GROUP BY bed_id", (since_ms,))
        return {r["bed_id"]: int(r["n"]) for r in rows}


def _bed_of(rec: dict) -> str | None:
    b = (rec.get("data") or {}).get("bed_id")
    return b if isinstance(b, str) else None


def _device_of(rec: dict) -> str | None:
    d = (rec.get("data") or {}).get("device_id")
    return d if isinstance(d, str) else None
