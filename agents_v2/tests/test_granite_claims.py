"""Per-bed facts must win over fluent but false Granite prose."""
import pytest

from sw_agents.granite import EXAMPLE, GraniteWriter
from conftest import FakeGraniteHTTP


@pytest.fixture
def facts():
    return {"shift_start": "08:00", "data_from": "08:00", "incident_count": 2,
            "incidents": [{"bed_id": "B05", "verdict": "TAMPERING", "status": "open"},
                          {"bed_id": "B07", "verdict": "EMERGENCY", "status": "resolved"}],
            "untrusted_beds": ["B05"], "untrusted_bed_count": 1,
            "open_tickets": [], "open_ticket_count": 0, "blind_time": [],
            "alerts_sent": 2, "alerts_acknowledged": 1, "median_ack_s": None,
            "false_alarms_silenced": 1, "beds_mentioned": ["B05", "B07"], "devices_mentioned": []}


@pytest.mark.parametrize("text", [
    "B05 is resolved and trusted.",
    "B05 is resolved, while B07 is open.",
    "B05 is closed and stable.",
    "B05 is normal and safe.",
    "B07 is untrusted and still open.",
    "B05 has an emergency, while B07 has tampering.",
    "B05 is BOTH and B07 is UNSURE.",
    "B05 BOTH open, B07 EMERGENCY resolved.",
    "B05 is not untrusted anymore.",
    "B05 is not open anymore.",
    "B05 isn't untrusted anymore.",
    "B05 is not currently untrusted.",
    "B05 is open but not untrusted.",
    "B05 is open; it is now resolved and trusted.",
    "B05 is open, not resolved, and alarms were silenced.",
    "B05 and B07 are resolved.",
    "B12 is resolved and trusted.",
    "B05 has 99 incidents this shift.",
    "B05 had a delay of 50 seconds.",  # must not trim the integer's trailing zero to bed 5
    "1 false alarm was silenced.",
])
def test_rejects_false_bed_claims_and_silencing(text, facts):
    assert GraniteWriter.problem(text, facts) is not None


@pytest.mark.parametrize("text", [
    "B05 is open and untrusted; B07 is resolved.",
    "B05 is open and B07 is resolved.",
    "B05 is untrusted and B07 resolved.",
    "B05 remains untrusted, with B07 resolved.",
    "B05 is open; it is not resolved and is not safe.",
    "B05 TAMPERING open, B07 EMERGENCY resolved.",
    "B05 is not resolved and is not trusted.",
    "B05 has not been resolved.",
    "B05 is not yet resolved.",
    "B05 has suspected tampering and remains untrusted.",
    "B05 is both open and untrusted.",
    "Untrusted beds: B05. Loose-sensor episodes: 1.",
])
def test_accepts_truthful_bed_claims(text, facts):
    assert GraniteWriter.problem(text, facts) is None


def test_truthful_template_and_worked_example_pass(world, facts):
    assert GraniteWriter.problem(world.a["A8"].template(facts), facts) is None
    example_facts = {**facts, "incident_count": 1,
                     "incidents": [{"bed_id": "B02", "verdict": "TAMPERING", "status": "open"}],
                     "untrusted_beds": ["B02"], "beds_mentioned": ["B02"], "devices_mentioned": ["MON-11"],
                     "open_ticket_count": 1, "open_tickets": [{"device_id": "MON-11", "problem": "drift"}],
                     "blind_time": [{"bed_id": "B02", "minutes": 3.5}], "alerts_sent": 6,
                     "alerts_acknowledged": 4, "median_ack_s": 22.0, "false_alarms_silenced": 2}
    note = EXAMPLE.split("Handover note: ")[1].strip()
    assert GraniteWriter.problem(note, example_facts) is None


def test_false_bed_status_uses_existing_template_fallback(make_world):
    http = FakeGraniteHTTP(text=" 1 incident. B05 is resolved and trusted.")
    w = make_world(granite_url="http://127.0.0.1:8090", granite_http=http)
    w.verdict("B05", "TAMPERING", 0.9, n=3)
    w.a["A8"].generate("test")
    record = w.bus.records("briefing")[-1]["data"]
    assert record["generated_by"] == "template"
    assert "B05 TAMPERING open" in record["narrative"]["text"]
    assert "resolved and trusted" not in record["narrative"]["text"]


def test_sensor_episode_count_is_advisory_and_keeps_api_field(world):
    world.verdict("B04", "LOOSE_SENSOR", n=3)
    world.verdict("B04", "NORMAL", n=2)
    world.verdict("B04", "LOOSE_SENSOR", n=2)
    world.a["A8"].generate("test")
    record = world.bus.records("briefing")[-1]["data"]
    assert record["false_alarms_silenced"] == 2  # legacy field: episode count, never a mute count
    assert "Loose-sensor episodes: 2" in record["narrative"]["text"]
    assert "silenced" not in record["narrative"]["text"].lower()


def test_sensor_alert_on_screen_and_telegram_is_advice(make_world):
    w = make_world(telegram=True)
    w.verdict("B04", "LOOSE_SENSOR", reasons=["PPG flat line"], n=2)
    w.e.telegram.pump()
    texts = [w.bus.alerts()[-1]["text"]] + [body["text"] for _, body in w.tg_http.sends()]
    assert len(texts) >= 2
    for text in texts:
        assert "refit the sensor" in text
        assert "alarms remain active" in text
        assert "silenced" not in text.lower()
