"""Phase A HTTP acceptance against the real ASGI application."""
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sw_common import make_action, make_alert, make_verdict, make_vitals, topic_for

from sw_api.config import Settings


def app_for(bus, clock, **settings):
    from sw_api.app import create_app
    return create_app(settings=replace(Settings(), **settings), bus=bus, clock=clock)


def login(client, role="nurse"):
    response = client.post("/api/session", json={"role": role})
    assert response.status_code == 200
    return response.json()["token"]


def ingest(app, message):
    assert app.state.runtime.ingest.process(message, topic_for(message))


def normal(clock, bed="B05", **fields):
    return make_verdict(bed_id=bed, window_start=clock.ms() // 5000 * 5000,
                        verdict="NORMAL", trust=1, confidence=1, scores={}, ts=clock.ms(), **fields)


def test_preview_public_and_ward_never_seen(bus, clock):
    with TestClient(app_for(bus, clock)) as client:
        assert client.get("/api/ward").status_code == 401
        preview = client.get("/api/ward/preview").json()
        assert [b["bed_id"] for b in preview["beds"]] == ["B01", "B02", "B03", "B04"]
        assert all("patient" not in b for b in preview["beds"])
        login(client)
        body = client.get("/api/ward").json()
        assert len(body["beds"]) == 12
        bed = body["beds"][0]
        assert bed["patient"]["initials"]
        assert bed["verdict"] == "UNSURE" and bed["reason"] == "Awaiting verdict"
        assert bed["trust_score"] == 0 and bed["is_trusted"] is False
        assert bed["vitals"] is None and bed["last_updated_at"] is None
        assert bed["connected"] is False and bed["last_trusted"] is None
        runtime = client.app.state.runtime
        assert runtime.state.beds["B01"].verdict is None
        assert runtime.store.verdicts == {} and runtime.store.scores == {}


def test_sessions_cookie_pin_bearer_query_expiry_and_demo_switch(bus, clock):
    with TestClient(app_for(bus, clock, session_ttl_s=2)) as client:
        response = client.post("/api/session", json={"username": "priya", "pin": "4821"})
        assert response.status_code == 200
        cookie = response.headers["set-cookie"]
        assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie
        token = response.json()["token"]
        assert response.json()["role"] == "nurse"
        client.cookies.clear()
        assert client.get("/api/ward", headers={"Authorization": f"Bearer {token}"}).status_code == 200
        assert client.get(f"/api/ward?token={token}").status_code == 200
        clock.advance(3)
        assert client.get(f"/api/ward?token={token}").status_code == 401
        assert client.post("/api/session", json={"username": "priya", "pin": "0000"}).status_code == 401
        assert client.post("/api/session", json={"role": "unknown"}).status_code == 422
    with TestClient(app_for(bus, clock, demo_role_login=False)) as client:
        assert client.post("/api/session", json={"role": "nurse"}).status_code == 403
        assert client.post("/api/session", json={"username": "admin", "pin": "9012"}).json()["role"] == "operator"


def test_auth_roles_origin_and_invalid_commands(bus, clock):
    with TestClient(app_for(bus, clock)) as client:
        assert client.post("/api/devices/MON-05/isolate", json={}).status_code == 401
        login(client)
        assert client.post("/api/devices/MON-05/isolate", json={}).status_code == 403
        assert client.post("/api/beds/B05/acknowledge", json={}).status_code == 409
        assert client.post("/api/beds/B99/acknowledge", json={}).status_code == 404
        assert client.post("/api/beds/B05/bedside-check", json={"type": "confirm_bedside", "bedId": "B06", "status": "patient_ok"}).status_code == 422
        assert client.post("/api/beds/B05/bedside-check", json={"status": "invented"}).status_code == 422
        assert client.post("/api/beds/B05/bedside-check", json={"result": "patient_ok"}, headers={"Origin": "https://evil.example"}).status_code == 403
        assert client.post("/api/session", json={"role": "operator"}, headers={"Origin": "https://evil.example"}).status_code == 403
        assert bus.sent == []


def test_isolate_receipt_queues_exactly_once_without_mutating_device(bus, clock):
    app = app_for(bus, clock)
    with TestClient(app) as client:
        login(client, "it")
        response = client.post("/api/devices/MON-05/isolate", json={"type": "isolate_device", "bedId": "B05", "deviceId": "MON-05", "by": "staff:forged"})
        assert response.status_code == 202
        receipt = response.json()
        assert receipt["command_id"] and receipt["accepted_at"] == clock.ms()
        assert receipt["request_id"]
        assert len(bus.sent) == 1
        message = bus.sent[0]
        assert (message["action"], message["target_id"], message["by"]) == ("isolate_device", "MON-05", "staff:sam")
        assert app.state.runtime.store.requests[receipt["request_id"]] == message
        devices = client.get("/api/devices").json()
        assert next(d for d in devices if d["device_id"] == "MON-05")["isolated"] is False
        ingest(app, make_action(action_id="iso", by="A2", action="disable_client", bed_id="B05", ts=clock.ms(), undo_id="iso"))
        assert client.get("/api/devices").json()[4]["isolated"] is True


def test_bedside_check_persists_and_publishes_both_messages(bus, clock):
    app = app_for(bus, clock)
    with TestClient(app) as client:
        login(client)
        response = client.post("/api/beds/B05/bedside-check", json={"type": "confirm_bedside", "bedId": "B05", "status": "patient_not_ok", "notes": "checked", "by": "staff:forged"})
        assert response.status_code == 201 and response.json()["command_id"]
        assert [m["type"] for m in bus.sent] == ["bedside_check", "action"]
        assert bus.sent[0]["result"] == "patient_not_ok"
        assert all(m["by"] == "staff:priya" for m in bus.sent)
        assert len(app.state.runtime.store.bedside) == 1
        assert app.state.runtime.state.beds["B05"].last_bedside["result"] == "patient_not_ok"
        assert client.get("/api/actions").json()["actions"][0]["action_code"] == "bedside_check"


def test_ack_selects_priority_then_newest_and_escalation_validates_bed(bus, clock):
    app = app_for(bus, clock)
    with TestClient(app) as client:
        login(client)
        for aid, priority, ts in [("low", "low", clock.ms()+10), ("old", "high", clock.ms()), ("new", "high", clock.ms()+1)]:
            ingest(app, make_alert(alert_id=aid, bed_id="B05", verdict="EMERGENCY", priority=priority, text="check", to=[], ts=ts))
        assert client.post("/api/beds/B05/acknowledge", json={"type": "acknowledge_alert", "bedId": "B05"}).status_code == 202
        assert bus.sent[-1]["target_id"] == "new"
        assert app.state.runtime.state.alerts["new"]["status"] == "open"
        assert client.post("/api/alerts/new/escalate", json={"type": "escalate_alert", "alertId": "new", "bedId": "B06"}).status_code == 422
        assert client.post("/api/alerts/new/escalate", json={"type": "escalate_alert", "alertId": "new", "bedId": "B05"}).status_code == 202
        assert bus.sent[-1]["action"] == "escalate_alert"
        assert client.post("/api/alerts/missing/escalate", json={}).status_code == 404


def test_undo_checks_original_exists_scope_and_undoability(bus, clock):
    app = app_for(bus, clock)
    with TestClient(app) as client:
        login(client, "it")
        assert client.post("/api/actions/unknown/undo", json={}).status_code == 404
        ingest(app, make_action(action_id="iso", by="A2", action="disable_client", bed_id="B05", undo_id="iso", ts=clock.ms()))
        assert client.post("/api/actions/iso/undo", json={"type": "undo_action", "originalActionId": "iso", "bedId": "B06"}).status_code == 422
        assert client.post("/api/actions/iso/undo", json={"type": "undo_action", "originalActionId": "iso", "bedId": "B05"}).status_code == 202
        assert bus.sent[-1]["action"] == "undo_action"
        assert app.state.runtime.state.device_brief("MON-05")["isolated"]
        log = client.get("/api/actions?limit=1").json()["actions"][0]
        assert log["id"] == "iso" and log["mode"] == "automatic" and log["undoable"]


def test_never_blank_zero_null_frozen_waveforms_offline_and_recovery(bus, clock):
    app = app_for(bus, clock)
    with TestClient(app) as client:
        login(client)
        ingest(app, normal(clock))
        ingest(app, make_vitals(bed_id="B05", seq=0, hr=0, spo2=None, ecg=[1.0]*125, ts=clock.ms()))
        before = client.get("/api/ward").json()["beds"][4]
        assert before["vitals"]["hr"] == 0 and before["vitals"]["spo2"] is None
        assert before["is_trusted"] and before["waveform"]["ppg"] == []
        cutoff = clock.ms()
        clock.advance(1)
        ingest(app, make_vitals(bed_id="B05", seq=1, hr=150, ecg=[9.0]*125, ts=clock.ms()))
        ingest(app, make_verdict(bed_id="B05", window_start=cutoff//5000*5000, verdict="BOTH", confidence=.9, trust=.1, scores={}, last_trusted_ts=cutoff, ts=clock.ms()))
        bed = client.get("/api/ward").json()["beds"][4]
        assert bed["vitals"]["hr"] == 0 and not bed["is_trusted"]
        assert bed["verdict"] == "BOTH" and bed["priority"] == "high"
        assert bed["last_trusted"]["captured_at"] == cutoff
        assert bed["waveform"]["ecg"] == [1.0]*25
        clock.advance(6)
        bed = client.get("/api/ward").json()["beds"][4]
        assert not bed["connected"] and bed["vitals"]["hr"] == 0
        ingest(app, normal(clock))
        ingest(app, make_vitals(bed_id="B05", seq=2, hr=80, ts=clock.ms()))
        assert client.get("/api/ward").json()["beds"][4]["is_trusted"]


def test_demo_control_reset_barrier_outbox_and_health(bus, clock):
    app = app_for(bus, clock)
    with TestClient(app) as client:
        login(client, "operator")
        ingest(app, normal(clock))
        old = make_vitals(bed_id="B05", seq=0, hr=80, ts=clock.ms())
        ingest(app, old)
        bus.accept = False
        response = client.post("/api/demo/run", json={"scenario": "replay_attack", "speed": 2, "start_at_s": 30})
        assert response.status_code == 202 and response.json()["accepted"]
        assert len(app.state.runtime.store.pending_publications()) == 1
        bus.accept = True
        client.portal.call(app.state.runtime.tick)
        assert bus.sent[-1]["scenario"] == "replay_attack" and bus.sent[-1]["speed"] == 2
        assert response.json()["run_id"] == "run_20261017_160000"
        assert client.post("/api/demo/reset", json={}).status_code == 202
        assert app.state.runtime.state.beds["B05"].last_point is None
        assert not app.state.runtime.ingest.process(old, topic_for(old))
        assert len(app.state.runtime.store.demo_runs) == 2
        health = client.get("/api/health").json()
        assert health["mqtt_connected"] and health["db_ok"] is False
        assert health["storage"] == "memory" and health["beds_online"] == 0
        assert client.get("/api/workload").status_code == 404  # Phase B
        assert client.post("/api/demo/run", json={"speed": 3}).status_code == 422


def test_static_frontend_and_spa_fallback_without_api_fallback(bus, clock, tmp_path):
    (tmp_path / "index.html").write_text("<html>ward screens</html>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("export {}")
    with TestClient(app_for(bus, clock, frontend_dist=tmp_path)) as client:
        assert "ward screens" in client.get("/").text
        assert "ward screens" in client.get("/ward").text
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/api/missing").status_code == 404
        assert client.get("/assets/missing.js").status_code == 404


def test_frozen_waveform_survives_untrusted_cache_eviction(bus, clock):
    app = app_for(bus, clock)
    with TestClient(app) as client:
        login(client)
        ingest(app, normal(clock))
        ingest(app, make_vitals(bed_id="B05", seq=1, hr=80, ecg=[2.0]*125, ts=clock.ms()))
        cutoff = clock.ms()
        clock.advance(1)
        ingest(app, make_verdict(bed_id="B05", window_start=cutoff//5000*5000, verdict="TAMPERING", confidence=1, trust=.1, scores={}, last_trusted_ts=cutoff, ts=clock.ms()))
        for seq in range(2, 70):
            clock.advance(1)
            ingest(app, make_vitals(bed_id="B05", seq=seq, hr=999, ecg=[9.0]*125, ts=clock.ms()))
        bed = client.get("/api/ward").json()["beds"][4]
        assert bed["vitals"]["hr"] == 80
        assert bed["waveform"]["ecg"] == [2.0]*25
        assert bed["last_trusted"]["waveform"]["ecg"] == [2.0]*25


def test_malformed_origin_rejected_without_server_error(bus, clock):
    with TestClient(app_for(bus, clock)) as client:
        response = client.post("/api/session", json={"role": "nurse"}, headers={"Origin": "http://["})
        assert response.status_code == 403
