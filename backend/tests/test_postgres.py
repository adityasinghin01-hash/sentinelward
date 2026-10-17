"""PostgreSQL store tests. They run only when SW_TEST_PG holds a DSN; that database is WIPED first.

    SW_TEST_PG=postgresql://localhost/sw_test .venv/bin/pytest -q backend/tests/test_postgres.py
"""
import os
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sw_common import make_action, make_alert, make_record, make_score, make_verdict, make_vitals, topic_for

from sw_api.config import Settings

DSN = os.environ.get("SW_TEST_PG")
pytestmark = [pytest.mark.pg, pytest.mark.skipif(not DSN, reason="set SW_TEST_PG to a disposable database DSN")]


def sql(query, params=()):
    import psycopg
    with psycopg.connect(DSN, autocommit=True) as conn:
        cur = conn.execute(query, params)
        return cur.fetchall() if cur.description else []


@pytest.fixture(autouse=True)
def wipe():
    sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")


def app_for(bus, clock):
    from sw_api.app import create_app
    return create_app(settings=replace(Settings(), pg_dsn=DSN), bus=bus, clock=clock)


def put(client, app, message):
    assert client.portal.call(app.state.runtime.ingest.process, message, topic_for(message))


def flush(client, app):
    assert client.portal.call(app.state.runtime.store.writer.flush)


def verdict(clock, value="NORMAL", last_trusted_ts=None):
    return make_verdict(bed_id="B05", window_start=clock.ms() // 5000 * 5000, verdict=value, confidence=1,
                        trust=1 if last_trusted_ts is None else .1, scores={}, last_trusted_ts=last_trusted_ts,
                        ts=clock.ms())


def test_schema_is_idempotent_and_ward_synced(bus, clock):
    for _ in range(2):
        with TestClient(app_for(bus, clock)) as client:
            assert client.get("/api/health").json()["db_ok"] is True
    assert sql("SELECT count(*) FROM beds")[0][0] == 12
    assert sql("SELECT initials FROM patients WHERE bed_id = 'B01'")[0][0] == "A.K."


def test_rows_persist_marks_apply_and_warm_start_restores_never_blank(bus, clock):
    app = app_for(bus, clock)
    with TestClient(app) as client:
        client.post("/api/session", json={"role": "nurse"})
        put(client, app, verdict(clock))
        good = clock.ms()
        put(client, app, make_vitals(bed_id="B05", seq=0, hr=0, spo2=97, ts=good))
        clock.advance(1)
        put(client, app, make_vitals(bed_id="B05", seq=1, hr=150, spo2=97, ts=clock.ms()))
        put(client, app, verdict(clock, "TAMPERING", last_trusted_ts=good))
        put(client, app, make_score(bed_id="B05", model="M2", model_version="v1", window_start=clock.ms() // 5000 * 5000,
                                    score=None, label="unavailable", reason=""))
        for status in ("open", "acked"):
            put(client, app, make_alert(alert_id="al", bed_id="B05", verdict="TAMPERING", text="t", to=[],
                                        status=status, ts=clock.ms()))
        put(client, app, make_record(kind="ticket", record_id="tk", by="A6", data={"bed_id": "B05", "status": "new"},
                                     ts=clock.ms()))
        flush(client, app)
        flush(client, app)  # again: retried batches change nothing
        assert sql("SELECT second, hr, trusted FROM vitals_1s ORDER BY ts") == [(good // 1000, 0, True),
                                                                                (good // 1000 + 1, 150, False)]
        assert sql("SELECT score FROM scores") == [(None,)]
        assert sql("SELECT status FROM alerts") == [("acked",)] and sql("SELECT count(*) FROM alert_history")[0][0] == 2
        assert sql("SELECT kind, version FROM records") == [("ticket", 1)]
    # Restart: the bed still shows the trusted values from before the cutoff.
    app = app_for(bus, clock)
    with TestClient(app) as client:
        client.post("/api/session", json={"role": "nurse"})
        bed = client.get("/api/ward").json()["beds"][4]
        assert bed["verdict"] == "TAMPERING" and bed["is_trusted"] is False
        assert bed["vitals"]["hr"] == 0 and bed["last_trusted"]["captured_at"] == good
        assert client.get("/api/tickets").json()[0]["record_id"] == "tk"
        assert client.get("/api/alerts").json()[0]["status"] == "acked"


def test_pin_older_than_ram_comes_from_database(bus, clock):
    app = app_for(bus, clock)
    with TestClient(app) as client:
        client.post("/api/session", json={"role": "nurse"})
        put(client, app, verdict(clock))
        old = clock.ms()
        put(client, app, make_vitals(bed_id="B05", seq=0, hr=61, ts=old))
        flush(client, app)
        runtime = app.state.runtime
        runtime.state.beds["B05"].points.clear()  # as if the point had aged out of the 30-minute buffer
        clock.advance(2)
        put(client, app, make_vitals(bed_id="B05", seq=1, hr=140, ts=clock.ms()))
        put(client, app, verdict(clock, "TAMPERING", last_trusted_ts=old))
        bed = client.get("/api/ward").json()["beds"][4]
        assert bed["vitals"]["hr"] == 61 and bed["last_trusted"]["captured_at"] == old


def test_outbox_survives_restart_and_reset_keeps_demo_runs(bus, clock):
    app = app_for(bus, clock)
    with TestClient(app) as client:
        client.post("/api/session", json={"role": "it"})
        bus.accept = False
        assert client.post("/api/devices/MON-05/isolate", json={}).status_code == 202
        flush(client, app)
        assert sql("SELECT count(*) FROM outbox WHERE sent_ts IS NULL")[0][0] == 1
        assert sql("SELECT action, target_id FROM requests") == [("isolate_device", "MON-05")]
    bus.accept = True
    app = app_for(bus, clock)
    with TestClient(app) as client:
        client.portal.call(app.state.runtime.tick)
        assert bus.sent[-1]["action"] == "isolate_device"
        flush(client, app)
        assert sql("SELECT count(*) FROM outbox WHERE sent_ts IS NULL")[0][0] == 0
        client.post("/api/session", json={"role": "operator"})
        put(client, app, make_vitals(bed_id="B05", seq=0, hr=70, ts=clock.ms()))
        assert client.post("/api/demo/run", json={"scenario": "emergency", "speed": 1}).status_code == 202
        clock.advance(1)
        old = make_vitals(bed_id="B05", seq=1, hr=71, ts=clock.ms())
        assert client.post("/api/demo/reset", json={}).status_code == 202
        flush(client, app)
        assert sql("SELECT count(*) FROM vitals_1s")[0][0] == 0
        assert sql("SELECT count(*) FROM requests")[0][0] == 0
        assert sorted(r[0] for r in sql("SELECT cmd FROM demo_runs")) == ["reset", "run"]
        assert sql("SELECT scenario, speed FROM demo_runs WHERE cmd = 'run'") == [("emergency", 1)]
    # After a restart the reset barrier still rejects retained pre-reset messages.
    app = app_for(bus, clock)
    with TestClient(app) as client:
        assert not client.portal.call(app.state.runtime.ingest.process, old, topic_for(old))


def test_failed_batch_retries_after_connection_loss(bus, clock):
    app = app_for(bus, clock)
    with TestClient(app) as client:
        writer = app.state.runtime.store.writer
        put(client, app, make_action(action_id="a1", by="A2", action="disable_client", bed_id="B03", ts=clock.ms()))
        flush(client, app)
        client.portal.call(writer._conn.close)  # simulate the server dropping the connection
        put(client, app, make_action(action_id="a1", by="A2", action="disable_client", bed_id="B03", result="failed",
                                     ts=clock.ms() + 1))
        flush(client, app)
        assert sql("SELECT result FROM actions") == [("failed",)]
        assert writer.ok


def test_history_beyond_ram_and_indexed_timing(bus, clock):
    app = app_for(bus, clock)
    with TestClient(app) as client:
        client.post("/api/session", json={"role": "nurse"})
        now = clock.ms()
        rows = [("B05", now - i * 1000, (now - i * 1000) // 1000, "MON-05", 70.0, True, now) for i in range(3600)]
        import psycopg
        with psycopg.connect(DSN) as conn:
            conn.cursor().executemany("INSERT INTO vitals_1s (bed_id, ts, second, device_id, hr, trusted, received_ts) "
                                      "VALUES (%s, %s, %s, %s, %s, %s, %s)", rows)
        start = time.perf_counter()
        points = client.get("/api/beds/B05/history?minutes=60").json()["points"]
        elapsed = time.perf_counter() - start
        assert len(points) == 3600 and points[0]["ts"] < points[-1]["ts"]
        print(f"60-minute history from PostgreSQL: {elapsed * 1000:.1f} ms (local machine, not LinuxONE)")
