"""Phase B HTTP routes against the real ASGI app (fake bus, memory store)."""
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sw_common import make_action, make_alert, make_net_features, make_record, make_verdict, make_vitals, topic_for

from sw_api.config import Settings


@pytest.fixture
def app(bus, clock):
    from sw_api.app import create_app
    return create_app(settings=replace(Settings()), bus=bus, clock=clock)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


def login(client, role):
    assert client.post("/api/session", json={"role": role}).status_code == 200


def ingest(app, message):
    assert app.state.runtime.ingest.process(message, topic_for(message))


def record(app, clock, kind, rid, data, by=None):
    owner = {"incident": "A3", "report": "A5", "ticket": "A6", "briefing": "A8", "workload": "A7"}[kind]
    ingest(app, make_record(kind=kind, record_id=rid, by=by or owner, data=data, ts=clock.ms()))


def test_bed_detail_and_history_zero_null_and_trust(app, client, clock):
    login(client, "nurse")
    ingest(app, make_verdict(bed_id="B03", window_start=clock.ms() // 5000 * 5000, verdict="NORMAL",
                             confidence=1, trust=1, scores={}, ts=clock.ms()))
    for i in range(3):
        ingest(app, make_vitals(bed_id="B03", seq=i, hr=0 if i == 0 else 70 + i, spo2=None, ts=clock.ms()))
        clock.advance(1)
    detail = client.get("/api/beds/B03").json()
    assert detail["bed_id"] == "B03" and detail["device"]["online"] is True
    assert len(detail["recent_verdicts"]) == 1 and detail["open_alerts"] == []
    points = client.get("/api/beds/B03/history?minutes=30").json()["points"]
    assert [p["hr"] for p in points] == [0, 71, 72]
    assert all(p["spo2"] is None and p["trusted"] for p in points)
    assert client.get("/api/beds/B99").status_code == 404
    assert client.get("/api/beds/B03/history?minutes=0").status_code == 422


def test_manual_reading_separate_from_monitor_and_publishes_action(app, client, bus, clock):
    login(client, "nurse")
    ingest(app, make_vitals(bed_id="B02", seq=0, hr=0, ts=clock.ms()))
    response = client.post("/api/beds/B02/manual-reading",
                           json={"type": "record_manual_reading", "bedId": "B02", "heartRate": 88, "spo2": 0,
                                 "notes": "radial pulse"})
    assert response.status_code == 201 and response.json()["command_id"]
    bed = client.get("/api/ward").json()["beds"][1]
    assert bed["vitals"]["hr"] == 0  # monitor value untouched
    assert bed["manual"]["hr"] == 88 and bed["manual"]["spo2"] == 0 and bed["manual"]["by"] == "staff:priya"
    assert bed["manual"]["sys"] is None
    assert bus.sent[-1]["action"] == "manual_reading" and bus.sent[-1]["by"] == "staff:priya"
    assert client.post("/api/beds/B02/manual-reading", json={"notes": "nothing"}).status_code == 422
    assert client.post("/api/beds/B02/manual-reading", json={"heartRate": 80, "hr": 81}).status_code == 422
    login(client, "it")
    assert client.post("/api/beds/B02/manual-reading", json={"hr": 80}).status_code == 403


def test_call_nurse_and_assignment_are_stored_pushed_and_never_published(app, client, bus):
    runtime = app.state.runtime
    client_ws = runtime.hub.subscribe([])
    login(client, "doctor")
    assert client.post("/api/beds/B04/call-nurse", json={"type": "call_bedside_nurse", "bedId": "B04",
                                                         "requestedBy": "someone else"}).status_code == 201
    call = runtime.state.beds["B04"].nurse_call
    assert call["by"] == "staff:dr_mehta" and call["status"] == "open"
    assert client.post("/api/beds/B04/assignment", json={"type": "assign_clinician", "bedId": "B04",
                                                         "clinicianId": "tom"}).status_code == 201
    assignment = runtime.state.beds["B04"].assignment
    assert assignment["staff_id"] == "staff:tom" and assignment["status"] == "assigned"
    assert client.post("/api/beds/B04/assignment", json={"clinicianId": "doctor-rao"}).status_code == 201
    assert runtime.state.beds["B04"].assignment["staff_id"] is None  # not a configured user: kept as sent
    assert client.post("/api/beds/B04/assignment/status", json={"type": "update_assignment", "bedId": "B04",
                                                                "status": "on_my_way"}).status_code == 200
    assert client.post("/api/beds/B04/assignment/status", json={"status": "flying"}).status_code == 422
    bed = client.get("/api/ward").json()["beds"][3]
    assert bed["assignment"]["status"] == "on_my_way" and bed["nurse_call"]["call_id"] == call["call_id"]
    assert [a["status"] for a in runtime.store.assignments] == ["assigned", "assigned", "on_my_way"]
    assert len(runtime.store.nurse_calls) == 1
    assert bus.sent == []
    assert client_ws.qsize >= 4  # each change pushed a bed.updated


def test_alert_list_dedup_and_ack_alias(app, client, bus, clock):
    login(client, "nurse")
    for status in ("open", "escalated", "open"):
        clock.advance(1)
        ingest(app, make_alert(alert_id="al1", bed_id="B06", verdict="EMERGENCY", text="check", to=[],
                               status=status, ts=clock.ms()))
    alerts = client.get("/api/alerts").json()
    assert len(alerts) == 1 and alerts[0]["status"] == "open"
    assert client.get("/api/alerts?status=open").json()[0]["alert_id"] == "al1"
    assert client.get("/api/alerts?status=nope").status_code == 422
    assert client.post("/api/alerts/al1/ack", json={}).status_code == 202
    assert (bus.sent[-1]["action"], bus.sent[-1]["target_id"]) == ("ack_alert", "al1")
    assert client.post("/api/alerts/zzz/ack", json={}).status_code == 404


def test_network_rows_and_fleet_hunt(app, client, bus, clock):
    login(client, "it")
    ws = clock.ms() // 5000 * 5000
    ingest(app, make_net_features(device_id="MON-07", window_start=ws, msgs_per_s=1.0, bytes_per_s=None,
                                  iat_mean_ms=1000, iat_std_ms=1, payload_mean=900, payload_std=0, senders=1,
                                  connects_per_s=0, malformed=0, seq_gaps=0, seq_repeats=0, stale_ms=0,
                                  new_field=7))
    rows = client.get("/api/devices/MON-07/network?minutes=10").json()
    assert len(rows) == 1 and rows[0]["new_field"] == 7 and rows[0]["bytes_per_s"] is None
    assert client.get("/api/devices/MON-99/network").status_code == 404
    response = client.post("/api/fleet-hunt", json={"type": "fleet_hunt", "model": "MX450"})
    assert response.status_code == 202 and response.json()["request_id"]
    assert (bus.sent[-1]["action"], bus.sent[-1]["target_id"], bus.sent[-1]["bed_id"]) == ("fleet_hunt", "MX450", None)
    login(client, "nurse")
    assert client.post("/api/fleet-hunt", json={"model": "MX450"}).status_code == 403


def test_incident_aliases_evidence_contain_resolve_and_review(app, client, bus, clock):
    login(client, "it")
    assert client.post("/api/incidents/B07/contain", json={"type": "contain_incident", "bedId": "B07"}).status_code == 404
    record(app, clock, "incident", "inc_1", {"bed_id": "B07", "device_id": "MON-07", "status": "pending", "evidence": []})
    assert client.get("/api/incidents").json()[0]["record_id"] == "inc_1"
    assert client.get("/api/incidents/B07").json()["record_id"] == "inc_1"
    assert client.get("/api/incidents/inc_1/evidence").json() == []
    response = client.post("/api/incidents/B07/evidence", json={"type": "capture_evidence", "bedId": "B07"})
    assert response.status_code == 201
    evidence = client.get("/api/incidents/inc_1/evidence").json()
    assert len(evidence) == 1 and len(evidence[0]["sha256"]) == 64 and evidence[0]["size_bytes"] > 0
    assert evidence[0]["captured_by"] == "staff:sam"
    audit = app.state.runtime.store.record_audit[-1]
    assert audit["field"] == "evidence" and audit["by"] == "staff:sam"
    assert client.post("/api/incidents/B07/contain", json={"type": "contain_incident", "bedId": "B08"}).status_code == 422
    assert client.post("/api/incidents/B07/contain", json={"type": "contain_incident", "bedId": "B07"}).status_code == 202
    assert (bus.sent[-1]["action"], bus.sent[-1]["target_id"], bus.sent[-1]["bed_id"]) == ("contain_incident", "inc_1", "B07")
    assert client.post("/api/incidents/B07/resolve", json={"type": "resolve_incident", "bedId": "B07",
                                                           "reason": "firmware reflashed"}).status_code == 202
    assert bus.sent[-1]["action"] == "resolve_incident" and bus.sent[-1]["note"] == "firmware reflashed"
    assert client.post("/api/incidents/inc_1/report/review", json={"type": "review_report"}).status_code == 404
    record(app, clock, "report", "rep_1", {"incident_id": "inc_1", "status": "draft"})
    assert client.post("/api/incidents/inc_1/report/review", json={"type": "review_report",
                                                                   "incidentId": "inc_1"}).status_code == 202
    assert (bus.sent[-1]["action"], bus.sent[-1]["target_id"], bus.sent[-1]["bed_id"]) == ("review_report", "rep_1", "B07")
    # A second unresolved incident on the same bed makes the bed alias ambiguous.
    record(app, clock, "incident", "inc_2", {"bed_id": "B07", "status": "pending", "evidence": []})
    assert client.post("/api/incidents/B07/contain", json={}).status_code == 409
    login(client, "nurse")
    assert client.post("/api/incidents/inc_1/contain", json={}).status_code == 403


def test_reports_save_audit_mark_sent_and_agent_replacement(app, client, bus, clock):
    login(client, "it")
    record(app, clock, "incident", "inc_9", {"bed_id": "B09", "status": "pending", "evidence": []})
    record(app, clock, "report", "rep_9", {"incident_id": "inc_9", "status": "draft", "organisation": None})
    draft = {"incidentId": "inc_9", "organisation": "Demo Hospital", "description": "Replay", "factsChecked": True,
             "savedAt": 1, "sentAt": None, "sentBy": "forged"}
    response = client.patch("/api/reports/inc_9", json={"type": "save_report", "incidentId": "inc_9", "report": draft})
    assert response.status_code == 200
    rep = client.get("/api/reports/rep_9").json()
    assert rep["data"]["organisation"] == "Demo Hospital" and rep["data"]["saved_by"] == "staff:sam"
    assert "sentBy" not in rep["data"] and rep["version"] == 2
    fields = {a["field"] for a in app.state.runtime.store.record_audit}
    assert {"organisation", "description", "factsChecked"} <= fields
    assert client.post("/api/reports/rep_9", json={"data": {"description": "Replay attack"}}).status_code == 200
    assert client.patch("/api/reports/rep_9", json={"report": {}, "data": {}}).status_code == 422
    assert client.post("/api/reports/inc_9/mark-sent", json={"type": "mark_report_sent", "sentBy": "x"}).status_code == 200
    assert bus.sent[-1]["action"] == "mark_report_sent" and bus.sent[-1]["by"] == "staff:sam"
    assert bus.sent[-1]["bed_id"] == "B09"
    assert client.get("/api/reports/rep_9").json()["data"]["status"] == "sent"
    assert client.post("/api/reports/rep_9/mark-sent", json={}).status_code == 409
    assert client.patch("/api/reports/rep_9", json={"data": {"description": "late"}}).status_code == 409
    # The agent republishing the same record_id wins; the audit rows stay.
    audits = len(app.state.runtime.store.record_audit)
    clock.advance(1)
    record(app, clock, "report", "rep_9", {"incident_id": "inc_9", "status": "needs_review"})
    assert client.get("/api/reports/rep_9").json()["data"]["status"] == "needs_review"
    assert len(app.state.runtime.store.record_audit) == audits + 1
    login(client, "nurse")
    assert client.patch("/api/reports/rep_9", json={"data": {"x": 1}}).status_code == 403


def test_tickets_create_list_patch_with_audit(app, client, clock):
    login(client, "nurse")
    response = client.post("/api/tickets", json={"type": "create_ticket", "bedId": "B10", "issue": "Loose SpO2 clip"})
    assert response.status_code == 201
    tid = response.json()["command_id"]
    tickets = client.get("/api/tickets").json()
    assert tickets[0]["record_id"] == tid and tickets[0]["by"] == "staff:priya"
    assert tickets[0]["data"]["device_id"] == "MON-10" and tickets[0]["data"]["status"] == "open"
    assert client.post("/api/tickets", json={"bedId": "B99", "issue": "x"}).status_code == 404
    assert client.patch(f"/api/tickets/{tid}", json={"status": "resolved"}).status_code == 403
    login(client, "biomedical")
    assert client.patch(f"/api/tickets/{tid}", json={"type": "update_ticket", "ticketId": tid, "status": "assigned",
                                                     "note": "on it"}).status_code == 200
    assert client.get("/api/tickets?status=assigned").json()[0]["data"]["note"] == "on it"
    assert [a["field"] for a in app.state.runtime.store.record_audit] == ["status", "note"]
    assert client.patch(f"/api/tickets/{tid}", json={"ticketId": "other", "status": "open"}).status_code == 422
    assert client.patch("/api/tickets/missing", json={"status": "open"}).status_code == 404


def test_briefing_projection_since_and_workload(app, client, clock):
    login(client, "doctor")
    assert client.get("/api/briefing").status_code == 503
    assert client.get("/api/workload?hours=2").json() == {"nurses": []}
    start = clock.ms()
    record(app, clock, "incident", "inc_b", {"bed_id": "B01", "status": "pending", "evidence": []})
    record(app, clock, "ticket", "tk_b", {"bed_id": "B02", "status": "new"})
    record(app, clock, "briefing", "br_1", {"since": start, "narrative": {"text": "Quiet shift.", "generator": "granite"}})
    record(app, clock, "workload", "wl_1", {"since": start, "nurses": [{"staff_id": "staff:priya", "count": 41},
                                                                        {"staff_id": "staff:ghost", "count": 3},
                                                                        {"bad": True}]})
    body = client.get("/api/briefing?since=" + "2026-10-17T16:00:00Z").json()
    assert body["generated_by"] == "IBM Granite" and body["summary"] == "Quiet shift."
    assert body["since"] == "2026-10-17T16:00:00.000Z"
    assert body["incidents"] == 1 and body["open_tickets"] == 1 and body["blind_time"] == []
    assert client.get(f"/api/briefing?since={start}").json()["record_id"] == "br_1"
    assert client.get(f"/api/briefing?since={start + 1}").status_code == 503
    assert client.get("/api/briefing?since=yesterday").status_code == 422
    nurses = client.get("/api/workload?hours=2").json()["nurses"]
    assert nurses == [{"nurse_id": "staff:priya", "nurse_name": "Priya (Nurse)", "alarms_last_2h": 41},
                      {"nurse_id": "staff:ghost", "nurse_name": "staff:ghost", "alarms_last_2h": 3}]
    clock.advance(3 * 3600)
    assert client.get("/api/workload?hours=2").status_code == 401
    login(client, "doctor")  # The workload window outlives the 30-minute idle session.
    assert client.get("/api/workload?hours=2").json() == {"nurses": []}
    # A template (non-Granite) briefing is reported as such, never as IBM Granite.
    record(app, clock, "briefing", "br_2", {"narrative": {"text": "Fallback.", "generator": "template"}})
    assert client.get("/api/briefing").json()["generated_by"] == "template"


def test_blind_time_counts_untrusted_seconds(app, client, clock):
    login(client, "nurse")
    start = clock.ms()
    for i in range(3):
        ingest(app, make_vitals(bed_id="B05", seq=i, hr=80, ts=clock.ms()))  # no verdict yet: untrusted
        clock.advance(1)
    record(app, clock, "briefing", "br", {"narrative": {"text": "x", "generator": "granite"}})
    body = client.get(f"/api/briefing?since={start}").json()
    assert body["blind_time"] == [{"bed_id": "B05", "minutes": 0.05}]
    assert body["untrusted_beds"] == 1


def test_action_result_update_replaces_and_failed_isolation_is_lifted(app, client, clock):
    runtime = app.state.runtime
    login(client, "it")
    pending = make_action(action_id="act_iso", by="A2", action="disable_client", bed_id="B08", device_id="MON-08",
                          undo_id="act_iso", result="pending", ts=clock.ms())
    ingest(app, pending)
    assert runtime.state.device_brief("MON-08")["isolated"]
    clock.advance(1)
    ingest(app, {**pending, "result": "failed", "ts": clock.ms()})
    assert not runtime.state.device_brief("MON-08")["isolated"]
    log = client.get("/api/actions").json()["actions"]
    assert len(log) == 1 and log[0]["id"] == "act_iso" and log[0]["undoable"] is False
    assert runtime.store.actions["act_iso"]["result"] == "failed"
    # An undo that later fails puts the isolation back in force.
    clock.advance(1)
    ingest(app, make_action(action_id="iso2", by="A2", action="disable_client", bed_id="B08", undo_id="iso2", ts=clock.ms()))
    clock.advance(1)
    undo = make_action(action_id="undo2", by="A2", action="enable_client", bed_id="B08", undoes="iso2",
                       approved_by="staff:sam", result="pending", ts=clock.ms())
    ingest(app, undo)
    assert not runtime.state.device_brief("MON-08")["isolated"]
    clock.advance(1)
    ingest(app, {**undo, "result": "failed", "ts": clock.ms()})
    assert runtime.state.device_brief("MON-08")["isolated"]


def test_openapi_lists_every_screen_route(client):
    paths = client.get("/openapi.json").json()["paths"]
    expected = {
        "/api/ward": {"get"}, "/api/ward/preview": {"get"}, "/api/devices": {"get"}, "/api/actions": {"get"},
        "/api/briefing": {"get"}, "/api/workload": {"get"}, "/api/session": {"post"}, "/api/demo/run": {"post"},
        "/api/demo/reset": {"post"}, "/api/beds/{bed_id}/acknowledge": {"post"},
        "/api/beds/{bed_id}/bedside-check": {"post"}, "/api/beds/{bed_id}/manual-reading": {"post"},
        "/api/beds/{bed_id}/call-nurse": {"post"}, "/api/beds/{bed_id}/assignment": {"post"},
        "/api/beds/{bed_id}/assignment/status": {"post"}, "/api/alerts/{alert_id}/escalate": {"post"},
        "/api/devices/{device_id}/isolate": {"post"}, "/api/fleet-hunt": {"post"},
        "/api/actions/{action_id}/undo": {"post"}, "/api/incidents/{incident_id}/evidence": {"get", "post"},
        "/api/incidents/{incident_id}/contain": {"post"}, "/api/incidents/{incident_id}/resolve": {"post"},
        "/api/incidents/{incident_id}/report/review": {"post"}, "/api/tickets": {"get", "post"},
        "/api/tickets/{ticket_id}": {"patch"}, "/api/reports/{report_id}": {"get", "patch", "post"},
        "/api/reports/{report_id}/mark-sent": {"post"}, "/api/health": {"get"}, "/api/beds/{bed_id}": {"get"},
        "/api/beds/{bed_id}/history": {"get"}, "/api/alerts": {"get"}, "/api/alerts/{alert_id}/ack": {"post"},
        "/api/devices/{device_id}/network": {"get"}, "/api/incidents/{incident_id}": {"get"},
    }
    for path, methods in expected.items():
        assert path in paths, path
        assert methods <= set(paths[path]), path
