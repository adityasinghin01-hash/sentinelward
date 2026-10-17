"""The doc-12 ward script, compressed to its agent-visible moments (fake bus, fake clock)."""


def test_ward_script_key_moments(world):
    w = world
    w.demo("run", run_id="run_script", start_at_s=0)
    t0 = w.clock.now_ms()

    def at(mmss: str) -> None:
        m, s = (int(x) for x in mmss.split(":"))
        target = t0 + (m * 60 + s) * 1000
        if target > w.clock.now_ms():
            w.advance((target - w.clock.now_ms()) / 1000)

    for bed in ("B01", "B02", "B05", "B12"):
        w.verdict(bed, "NORMAL", 1.0)
    # T+05:00 B03 real VT -> EMERGENCY, step 1; nobody answers -> step 2 at 05:30; nurse 2 acks at 05:50
    at("05:00")
    w.verdict("B03", "EMERGENCY", 1.0, reasons=["Monitor alarm remains active"])
    b03 = w.bus.alerts()[-1]["alert_id"]
    at("05:30")
    assert w.bus.alerts(b03)[-1]["ladder_step"] == 2
    at("05:50")
    w.a["A1"].ack(b03, "staff:tom", "telegram")
    assert w.bus.alerts(b03)[-1]["status"] == "acked"
    # T+06:30 B04 false asystole -> LOOSE_SENSOR, low, false alarm silenced
    at("06:30")
    w.verdict("B04", "LOOSE_SENSOR", 0.9, reasons=["ECG lead off"], n=2)
    assert w.bus.alerts()[-1]["priority"] == "low"
    # T+10:10 B05 replay -> TAMPERING -> cut off, hand-check alert, evidence, CERT-In draft
    at("10:10")
    w.verdict("B05", "TAMPERING", 0.9, reasons=["Same 10 seconds seen 4 minutes ago (replay)"], n=2)
    cut_b05 = w.bus.actions("disable_client")[-1]
    assert cut_b05["device_id"] == "MON-05"
    assert [a for a in w.bus.alerts() if a["bed_id"] == "B05"][-1]["text"].startswith("Bed 5 — monitor can't be trusted.")
    assert any(r["data"]["bed_id"] == "B05" for r in w.bus.records("incident"))
    assert any(r["data"]["bed_id"] == "B05" for r in w.bus.records("report"))
    # T+11:06 B08 drift -> DRIFTING + biomed ticket
    at("11:06")
    w.verdict("B08", "DRIFTING", 0.9, n=2)
    assert w.bus.records("ticket")[-1]["data"]["device_id"] == "MON-08"
    # T+11:30 nurse taps Patient OK on B05: logged, stays isolated
    at("11:30")
    w.bedside("B05", "patient_ok")
    assert "MON-05" in w.a["A2"].contained
    # T+12:00 B11 network attack -> IT only, fleet hunt (after cut-off), evidence, report
    at("12:00")
    n_alerts = len(w.bus.alerts())
    w.verdict("B11", "DEVICE_ATTACK", 0.95, n=2)
    assert len(w.bus.alerts()) == n_alerts
    assert "after MON-11 was cut off" in w.bus.actions("list_devices")[-1]["detail"]
    # T+14:00 B07 BOTH: nurse alerted now (high) AND device cut off
    at("14:00")
    w.verdict("B07", "BOTH", 0.95, reasons=["Monitor alarm remains active", "Flood"])
    b07 = [a for a in w.bus.alerts() if a["bed_id"] == "B07"][-1]
    assert b07["priority"] == "high" and "MON-07" in w.a["A2"].contained
    w.verdict("B07", "TAMPERING", 0.95, n=6)
    assert [a for a in w.bus.alerts() if a["bed_id"] == "B07"][-1]["verdict"] == "BOTH"  # never cancelled
    # T+15:30 IT clicks Undo on B05's cut-off
    at("15:30")
    w.verdict("B05", "NORMAL", 1.0)
    w.request("undo_action", cut_b05["action_id"], by="staff:sam")
    en = [a for a in w.bus.actions("enable_client") if a["undoes"] == cut_b05["action_id"]][-1]
    assert en["undoes"] == cut_b05["action_id"] and "MON-05" not in w.a["A2"].contained
    # T+17:00 B12 second sender -> UNSURE -> hand-check; T+18:00 Patient OK -> NORMAL
    at("17:00")
    w.verdict("B12", "UNSURE", 0.6, scores={"M4": 0.6, "M5": 0.6}, n=2)
    b12 = w.bus.alerts()[-1]
    assert b12["bed_id"] == "B12" and b12["priority"] == "medium"
    at("18:00")
    w.bedside("B12", "patient_ok")
    w.verdict("B12", "NORMAL", 1.0, n=4)  # an UNSURE alert closes after 4 NORMALs
    assert w.bus.alerts(b12["alert_id"])[-1]["status"] == "closed"
    # T+19:00 A8 writes the shift briefing from these 20 minutes
    at("19:00")
    brief = w.bus.records("briefing")[-1]["data"]
    assert brief["trigger"] == "ward script T+19:00"
    assert brief["incident_count"] == 3 and brief["untrusted_beds"] == ["B07", "B11"]
    # B01/B02 never alerted
    assert not [a for a in w.bus.alerts() if a["bed_id"] in ("B01", "B02")]
    # T+20:00 reset clears everything
    at("20:00")
    w.demo("reset")
    assert w.a["A2"].contained == {} and w.a["A1"].current == {}
    # every automatic action that changes state can be undone (messages/evidence are not undoable by design)
    undoable = {"set_bed_untrusted", "disable_client", "set_watch_level", "open_ticket", "record_ack", "warn_workload"}
    for a in w.bus.of("action"):
        if a["action"] in undoable and a["undoes"] is None and a["result"] != "failed" and "expired" not in a["detail"]:
            assert a["undo_id"] == a["action_id"], a
