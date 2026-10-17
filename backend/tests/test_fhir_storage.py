"""Offline persisted-history coverage: execute export SELECTs on a real SQLite store.

Only PostgreSQL bind syntax/cast is translated. This checks query/window semantics;
it does not claim live PostgreSQL/psycopg integration (the optional pg suite does that).
"""
import copy
import json
import sqlite3
from types import SimpleNamespace

from fastapi.testclient import TestClient

from sw_api.app import create_app
from sw_api.config import Settings
from sw_api.postgres import SQL_VERDICT
from sw_api.store import MemoryStore, WarmStart
from sw_api.writer import BatchWriter
from test_api import ingest, login
from test_fhir import START, alert, fetch, resources, verdict


class SqlFixtureStore(MemoryStore):
    durable = True

    def __init__(self, messages=()):
        super().__init__()
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.execute("CREATE TABLE verdicts (bed_id TEXT, ts INTEGER, verdict TEXT, msg TEXT)")
        self.db.execute("CREATE TABLE alerts (bed_id TEXT, ts INTEGER, msg TEXT)")
        for m in messages:
            table = "verdicts" if m["type"] == "verdict" else "alerts"
            if table == "verdicts":
                self.db.execute("INSERT INTO verdicts VALUES (?, ?, ?, ?)", (m["bed_id"], m["ts"], m["verdict"], json.dumps(m)))
            else:
                self.db.execute("INSERT INTO alerts VALUES (?, ?, ?)", (m["bed_id"], m["ts"], json.dumps(m)))
        self.fail = False
        self.on_query = None
        self.writer = BatchWriter(self.no_connection)

    async def no_connection(self):
        raise RuntimeError("Offline fixture never connects")

    async def start(self):
        # Cold process: SQL is the only source for historical verdicts and alerts.
        return WarmStart()

    async def close(self):
        self.db.close()

    async def _query(self, sql, params=()):
        if self.fail:
            raise RuntimeError("Injected DB read failure")
        if self.on_query:
            callback, self.on_query = self.on_query, None
            callback()
        translated = sql.replace("%s::text", "?").replace("%s", "?")
        return [{"msg": json.loads(row[0])} for row in self.db.execute(translated, params).fetchall()]

    def save(self, message, *args):
        if message["type"] == "verdict":
            # PostgresStore queues the unchanged message in the last Jsonb argument.
            self.writer.put(SQL_VERDICT, (SimpleNamespace(obj=copy.deepcopy(message)),))
        else:
            super().save(message, *args)


def test_persisted_verdicts_alerts_since_predecessor_and_bed(bus, clock):
    old = verdict(clock, "NORMAL")
    clock.advance(5)
    repeated = verdict(clock, "NORMAL")
    clock.advance(5)
    changed = verdict(clock, "EMERGENCY")
    other = verdict(clock, "BOTH", bed="B02")
    closed = alert(clock, status="closed")
    store = SqlFixtureStore([old, repeated, changed, other, closed])
    app = create_app(settings=Settings(), bus=bus, clock=clock, store=store)
    with TestClient(app) as client:
        login(client)
        body = fetch(client, f"?since={START+1}&bed=B01")
        obs, = resources(body, "Observation")
        assert obs["valueCodeableConcept"]["coding"][0]["code"] == "EMERGENCY"
        assert len(resources(body, "Device")) == 1
        issue, = resources(body, "DetectedIssue")
        assert issue["extension"][0]["valueCode"] == "resolved"
        assert len(resources(fetch(client), "Observation")) == 3
        assert not resources(fetch(client, f"?since={clock.ms()+1}"), "Observation")


def test_unflushed_verdicts_beyond_short_ward_buffer_are_not_lost(bus, clock):
    store = SqlFixtureStore()
    app = create_app(settings=Settings(), bus=bus, clock=clock, store=store)
    with TestClient(app) as client:
        login(client)
        for i in range(15):
            ingest(app, verdict(clock, "NORMAL" if i % 2 == 0 else "EMERGENCY"))
            clock.advance(5)
        assert len(resources(fetch(client, "?bed=B01"), "Observation")) == 15


def test_database_failure_is_explicit_not_partial_success(bus, clock):
    store = SqlFixtureStore()
    store.fail = True
    app = create_app(settings=Settings(), bus=bus, clock=clock, store=store)
    with TestClient(app) as client:
        login(client)
        response = client.get("/api/fhir/Bundle")
        assert response.status_code == 503
        assert "Injected" not in response.text
        assert client.get("/api/fhir/metadata").status_code == 200


def test_concurrent_reset_rejects_mixed_generation_export(bus, clock):
    store = SqlFixtureStore([verdict(clock)])
    app = create_app(settings=Settings(), bus=bus, clock=clock, store=store)
    with TestClient(app) as client:
        login(client)
        store.on_query = app.state.runtime.ingest.reset
        assert client.get("/api/fhir/Bundle").status_code == 409
        assert not resources(fetch(client), "Observation")  # pre-reset SQL row is excluded


def test_old_persisted_matching_verdict_supports_later_alert_update(bus, clock):
    emergency = verdict(clock, "EMERGENCY")
    clock.advance(5)
    normal = verdict(clock, "NORMAL")
    clock.advance(60)
    acknowledged = alert(clock, status="acked")
    store = SqlFixtureStore([emergency, normal, acknowledged])
    app = create_app(settings=Settings(), bus=bus, clock=clock, store=store)
    with TestClient(app) as client:
        login(client)
        obs, = resources(fetch(client, f"?since={clock.ms()}&bed=B01"), "Observation")
        assert obs["effectiveDateTime"] == "2026-10-17T16:00:00.000Z"
        assert obs["component"][0]["valueQuantity"]["value"] == emergency["scores"]["M1"]
