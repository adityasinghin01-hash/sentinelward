"""Ingestion validation, callback isolation, persistence and reset ordering."""
import asyncio
import threading

from sw_common import make_action, make_alert, make_record, make_score, make_vitals, topic_for


def test_invalid_message_counted_once_and_valid_message_survives(bus, clock, caplog):
    from sw_api.app import create_app
    runtime = create_app(bus=bus, clock=clock).state.runtime
    message = make_vitals(bed_id="B05", seq=1, hr=0, ts=clock.ms())
    assert not runtime.ingest.process({"type": "vitals"}, "ward/bed/B05/vitals")
    assert not runtime.ingest.process({"type": "vitals"}, "ward/bed/B05/vitals")
    assert runtime.ingest.invalid == 2
    assert len([r for r in caplog.records if "invalid message" in r.message]) == 1
    assert not runtime.ingest.process(message, "ward/bed/B06/vitals")
    assert runtime.ingest.process(message, topic_for(message))
    assert runtime.state.beds["B05"].last_point.hr == 0
    assert runtime.store.vitals[("B05", clock.ms()//1000)]["hr"] == 0


def test_thread_callback_copies_and_generation_drops_queued_pre_reset(bus, clock):
    from sw_api.app import create_app
    runtime = create_app(bus=bus, clock=clock).state.runtime
    async def run():
        runtime.ingest.bind(asyncio.get_running_loop())
        message = make_vitals(bed_id="B05", seq=1, hr=80, ts=clock.ms())
        thread = threading.Thread(target=runtime.ingest.callback, args=(message, topic_for(message)))
        thread.start()
        thread.join()
        message["hr"] = 999
        await asyncio.sleep(0)
        assert runtime.state.beds["B05"].last_point.hr == 80
        thread = threading.Thread(target=runtime.ingest.callback, args=(message, topic_for(message)))
        thread.start()
        thread.join()
        runtime.reset()
        await asyncio.sleep(0)
        assert runtime.state.beds["B05"].last_point is None
    asyncio.run(run())


def test_store_deduplicates_and_preserves_raw_null_scores_and_audited_replacements(bus, clock):
    from sw_api.app import create_app
    runtime = create_app(bus=bus, clock=clock).state.runtime
    def put(message):
        assert runtime.ingest.process(message, topic_for(message))
    score = make_score(bed_id="B05", model="M1", model_version="v1", window_start=clock.ms()//5000*5000,
                       score=None, label="unavailable", reason="No signal")
    put(score)
    assert runtime.store.scores[("B05", "M1", score["window_start"])]["score"] is None
    for status in ["open", "escalated", "acked"]:
        put(make_alert(alert_id="a", bed_id="B05", verdict="EMERGENCY", text="check", to=[], status=status, ts=clock.ms()))
    assert len(runtime.store.alerts) == 1 and len(runtime.store.alert_history) == 3
    rec = make_record(kind="ticket", record_id="r", by="A6", data={"bed_id": "B05", "status": "open"}, ts=clock.ms())
    put(rec)
    runtime.state.patch_record("r", {"status": "assigned"}, "staff:lena")
    rec["data"]["status"] = "resolved"
    put(rec)
    assert runtime.state.records["r"]["data"]["status"] == "resolved"
    assert runtime.store.record_audit[-1]["old"]["data"]["status"] == "assigned"
    assert runtime.store.record_audit[-1]["new"]["data"]["status"] == "resolved"


def test_failed_publication_retries_without_repeating_successful_sibling(bus, clock):
    from sw_api.app import create_app
    from sw_common import make_bedside_check
    runtime = create_app(bus=bus, clock=clock).state.runtime
    first = make_bedside_check(bed_id="B05", by="staff:priya", result="patient_ok", ts=clock.ms())
    second = make_action(action_id="a", by="staff:priya", action="bedside_check", bed_id="B05", ts=clock.ms())
    runtime.store.enqueue(first)
    runtime.store.enqueue(second)
    original = bus.publish
    def publish(message):
        return False if message["type"] == "action" else original(message)
    bus.publish = publish
    runtime.publish_pending()
    assert len(bus.sent) == 1 and len(runtime.store.pending_publications()) == 1
    bus.publish = original
    runtime.publish_pending()
    assert [m["type"] for m in bus.sent] == ["bedside_check", "action"]


def test_disconnected_bus_keeps_publications_out_of_paho_and_reset_discards_them(bus, clock):
    from sw_api.app import create_app
    from sw_common import make_request
    runtime = create_app(bus=bus, clock=clock).state.runtime
    bus.is_connected = False
    message = make_request(request_id="old", by="staff:sam", action="isolate_device", target_id="MON-05", bed_id="B05", ts=clock.ms())
    runtime.store.enqueue(message)
    runtime.publish_pending()
    assert bus.sent == []
    assert len(runtime.store.pending_publications()) == 1
    runtime.reset()
    bus.is_connected = True
    runtime.publish_pending()
    assert bus.sent == []
