"""FHIR acceptance through the real ASGI app and normal ingest path; no network."""
import copy
from dataclasses import replace
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sw_common import make_action, make_alert, make_verdict

from fhir_validator import validate_bundle
from test_api import app_for, ingest, login

START = 1792252800000
SCORES = {f"M{i}": value for i, value in enumerate((.03, .98, .12, .04, .07, .01), 1)}


def verdict(clock, value="EMERGENCY", bed="B01", scores=None, reasons=None):
    return make_verdict(bed_id=bed, window_start=clock.ms() // 5000 * 5000, verdict=value,
                        confidence=.97, trust=.95, scores=SCORES if scores is None else scores,
                        reasons=reasons or ["Sustained physiological deterioration; check patient at bedside."],
                        ts=clock.ms())


def alert(clock, value="EMERGENCY", bed="B01", status="open", aid="alert-01"):
    return make_alert(alert_id=aid, bed_id=bed, verdict=value, status=status,
                      text="Check patient at bedside; monitor evidence requires review.", to=["staff:priya"], ts=clock.ms())


def resources(bundle, kind):
    return [e["resource"] for e in bundle.get("entry", []) if e["resource"]["resourceType"] == kind]


def fetch(client, query=""):
    response = client.get("/api/fhir/Bundle" + query)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/fhir+json"
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    validate_bundle(body)
    return body


def test_empty_ward_and_metadata(bus, clock):
    with TestClient(app_for(bus, clock)) as client:
        login(client)
        body = fetch(client)
        assert not resources(body, "Observation") and not resources(body, "DetectedIssue")
        assert len(resources(body, "Device")) == 12
        metadata = client.get("/api/fhir/metadata")
        assert metadata.status_code == 200
        cap = metadata.json()
        assert cap["resourceType"] == "CapabilityStatement" and cap["fhirVersion"] == "4.0.1"
        assert cap["status"] == "active" and cap["kind"] == "instance"
        assert cap["date"] and cap["format"] == ["json"]
        assert cap["implementation"]["description"]
        assert cap["rest"][0]["mode"] == "server"
        advertised = json.dumps(cap)
        assert "/api/fhir/Bundle" in advertised and "/api/fhir/metadata" in advertised
        assert {r["type"] for r in cap["rest"][0]["resource"]} == {"Bundle", "Observation", "DetectedIssue", "Device"}


@pytest.mark.parametrize("value,cutoff,severity", [("EMERGENCY", False, "high"), ("TAMPERING", True, "moderate"),
                                                   ("BOTH", False, "high"), ("DEVICE_ATTACK", True, "moderate")])
def test_verdict_alert_device_and_no_side_effects(bus, clock, value, cutoff, severity):
    app = app_for(bus, clock)
    with TestClient(app) as client:
        login(client)
        ingest(app, verdict(clock, value))
        ingest(app, alert(clock, value))
        if cutoff:
            ingest(app, make_action(action_id="cut", action="disable_client", by="A2", bed_id="B01", ts=clock.ms()))
        runtime = app.state.runtime
        before = copy.deepcopy((runtime.store.verdicts, runtime.store.alerts, runtime.store.actions, bus.sent))
        body = fetch(client, "?bed=B01")
        obs, = resources(body, "Observation")
        assert obs["valueCodeableConcept"]["coding"][0]["code"] == value
        assert obs["code"]["text"] == "SentinelWard verdict"
        assert [c["valueQuantity"]["value"] for c in obs["component"]] == list(SCORES.values())
        issue, = resources(body, "DetectedIssue")
        assert issue["severity"] == severity and issue["extension"][0]["valueCode"] == "open"
        device, = resources(body, "Device")
        assert device["identifier"][0]["value"] == "MON-01"
        assert device["status"] == ("inactive" if cutoff else "active")
        assert before == (runtime.store.verdicts, runtime.store.alerts, runtime.store.actions, bus.sent)


@pytest.mark.parametrize("state,local,fhir", [("open", "open", "preliminary"), ("escalated", "open", "preliminary"),
                                             ("acked", "acknowledged", "preliminary"), ("closed", "resolved", "final")])
def test_alert_state_mapping_including_resolved(bus, clock, state, local, fhir):
    app = app_for(bus, clock)
    with TestClient(app) as client:
        login(client)
        ingest(app, verdict(clock))
        ingest(app, alert(clock))
        clock.advance(5)
        ingest(app, alert(clock, status=state))
        body = fetch(client, f"?since={clock.ms()}&bed=B01")
        issue, = resources(body, "DetectedIssue")
        assert issue["extension"][0]["valueCode"] == local and issue["status"] == fhir
        assert len(resources(body, "Observation")) == 1  # context for alert even before since
        assert not resources(fetch(client, f"?since={clock.ms()+1}"), "DetectedIssue")


def test_since_bed_and_verdict_changes(bus, clock):
    app = app_for(bus, clock)
    with TestClient(app) as client:
        login(client)
        ingest(app, verdict(clock, "NORMAL"))
        clock.advance(5)
        ingest(app, verdict(clock, "NORMAL"))
        clock.advance(5)
        ingest(app, verdict(clock, "BOTH"))
        ingest(app, verdict(clock, "TAMPERING", bed="B02"))
        body = fetch(client, f"?since={START + 1}&bed=B01")
        assert [o["valueCodeableConcept"]["coding"][0]["code"] for o in resources(body, "Observation")] == ["BOTH"]
        assert len(resources(body, "Device")) == 1
        assert len(resources(fetch(client), "Observation")) == 3
        assert not resources(fetch(client, f"?since={clock.ms()+1}"), "Observation")


@pytest.mark.parametrize("value", ["NORMAL", "DRIFTING", "LOOSE_SENSOR", "UNSURE"])
def test_non_alert_verdicts_missing_scores_are_not_zero(bus, clock, value):
    app = app_for(bus, clock)
    with TestClient(app) as client:
        login(client)
        ingest(app, verdict(clock, value, scores={"M1": 0}))
        ingest(app, alert(clock, value))
        body = fetch(client)
        obs, = resources(body, "Observation")
        assert obs["component"][0]["valueQuantity"]["value"] == 0
        assert all("dataAbsentReason" in c for c in obs["component"][1:])
        assert not resources(body, "DetectedIssue")


def test_alert_without_verdict_is_exported_without_invented_scores(bus, clock):
    app = app_for(bus, clock)
    with TestClient(app) as client:
        login(client)
        ingest(app, alert(clock))
        obs, = resources(fetch(client), "Observation")
        assert all("dataAbsentReason" in c for c in obs["component"])


@pytest.mark.parametrize("path", ["/api/fhir/Bundle", "/api/fhir/metadata"])
def test_auth_cookie_bearer_query_expiry_all_read_roles(bus, clock, path):
    with TestClient(app_for(bus, clock, session_ttl_s=2)) as client:
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"Authorization": "Bearer invalid"}).status_code == 401
        for role in ("nurse", "doctor", "it", "biomedical", "operator"):
            token = login(client, role)
            assert client.get(path).status_code == 200
            client.cookies.clear()
            assert client.get(path, headers={"Authorization": f"Bearer {token}"}).status_code == 200
            assert client.get(path + "?token=" + token).status_code == 200
        clock.advance(3)
        assert client.get(path + "?token=" + token).status_code == 401


@pytest.mark.parametrize("query", ["?since=no", "?since=-1", "?since=1.5", "?since=253402300800000", "?bed=B00", "?bed=B13", "?bed=b01"])
def test_invalid_filters(bus, clock, query):
    with TestClient(app_for(bus, clock)) as client:
        login(client)
        assert client.get("/api/fhir/Bundle" + query).status_code == 422


def sample_fixture(app, clock):
    """Real message shapes: deterioration, replay cutoff, and a combined alert already resolved."""
    cases = [
        ("B01", "EMERGENCY", "emergency-01", "open", (.02, .98, .05, .02, .01, .01),
         "Physiological deterioration matches ECG and pulse evidence; check patient now."),
        ("B03", "TAMPERING", "replay-03", "acked", (.97, .02, .96, .99, .10, .02),
         "Repeated waveform and sequence evidence indicate replay; monitor cut off."),
        ("B05", "BOTH", "combined-05", "closed", (.02, .98, .94, .99, .20, .01),
         "Patient deterioration and replay evidence occurred together; bedside review completed."),
    ]
    for bed, value, aid, state, values, reason in cases:
        scores = {f"M{i}": score for i, score in enumerate(values, 1)}
        ingest(app, verdict(clock, value, bed=bed, scores=scores, reasons=[reason]))
        message = alert(clock, value, bed=bed, aid=aid, status=state)
        message["text"] = reason
        ingest(app, message)
    ingest(app, make_action(action_id="isolate-03", by="A2", action="disable_client", bed_id="B03", ts=clock.ms()))


def test_sample_matches_fixture_and_contains_no_patient_names(bus, clock):
    app = app_for(bus, clock)
    with TestClient(app) as client:
        login(client)
        sample_fixture(app, clock)
        body = fetch(client)
        serialized = json.dumps(body)
        for bed in app.state.runtime.state.beds.values():
            assert bed.cfg.initials not in serialized
        assert '"patient"' not in serialized and '"name"' not in serialized and '"initials"' not in serialized
        sample = Path(__file__).resolve().parents[2] / "docs/evidence/raw/fhir-sample-bundle.json"
        assert json.loads(sample.read_text()) == body


def test_known_patient_identifiers_are_redacted_even_in_reason(bus, clock):
    app = app_for(bus, clock)
    with TestClient(app) as client:
        login(client)
        bed = app.state.runtime.state.beds["B01"]
        bed.cfg = replace(bed.cfg, initials="Jane Patient")
        ingest(app, verdict(clock, reasons=["Jane Patient needs bedside review"]))
        msg = alert(clock)
        msg["text"] = "Jane Patient requires attention"
        ingest(app, msg)
        body = fetch(client)
        assert "Jane Patient" not in json.dumps(body)
        assert "[redacted]" in json.dumps(body)


@pytest.mark.parametrize("mutation", ["missing-code", "bad-status", "wrong-cardinality", "bad-score", "dangling-reference", "unknown-field"])
def test_strict_validator_rejects_invalid_exports(bus, clock, mutation):
    app = app_for(bus, clock)
    with TestClient(app) as client:
        login(client)
        ingest(app, verdict(clock))
        ingest(app, alert(clock))
        body = fetch(client)
        obs, = resources(body, "Observation")
        if mutation == "missing-code":
            del obs["code"]
        elif mutation == "bad-status":
            resources(body, "DetectedIssue")[0]["status"] = "open"
        elif mutation == "wrong-cardinality":
            obs["component"] = {}
        elif mutation == "bad-score":
            obs["component"][0]["valueQuantity"]["value"] = 2
        elif mutation == "dangling-reference":
            obs["device"]["reference"] = "urn:uuid:00000000-0000-0000-0000-000000000000"
        else:
            obs["patientName"] = "Jane Patient"
        with pytest.raises(AssertionError):
            validate_bundle(body)


def test_latest_same_timestamp_verdict_matches_real_ward(bus, clock):
    app = app_for(bus, clock)
    with TestClient(app) as client:
        login(client)
        ingest(app, verdict(clock, "NORMAL"))
        ingest(app, verdict(clock, "EMERGENCY"))
        assert client.get("/api/ward").json()["beds"][0]["verdict"] == "EMERGENCY"
        obs, = resources(fetch(client, "?bed=B01"), "Observation")
        assert obs["valueCodeableConcept"]["coding"][0]["code"] == "EMERGENCY"


def test_patient_identifier_is_redacted_after_plain_text_normalization(bus, clock):
    app = app_for(bus, clock)
    with TestClient(app) as client:
        login(client)
        bed = app.state.runtime.state.beds["B01"]
        bed.cfg = replace(bed.cfg, initials="Jane Patient")
        ingest(app, verdict(clock, reasons=["Jane <b>Patient</b> needs review"]))
        msg = alert(clock)
        msg["text"] = "Jane&nbsp; Patient requires attention"
        ingest(app, msg)
        text = json.dumps(fetch(client))
        assert "Jane" not in text and "Patient requires" not in text
        assert "[redacted]" in text
