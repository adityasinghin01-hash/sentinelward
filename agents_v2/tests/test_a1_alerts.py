"""A1: verdict -> alert table, one alert per episode, ladder timing, ack, escalate, bedside, undo."""
from sw_agents.agents.a1_alerts import is_learning


def test_emergency_alerts_assigned_nurse_at_once(world):
    world.verdict("B03", "EMERGENCY", 1.0, reasons=["Monitor alarm remains active"])
    alerts = world.bus.alerts()
    assert len(alerts) == 1
    a = alerts[0]
    assert (a["bed_id"], a["verdict"], a["priority"], a["to"], a["ladder_step"], a["status"]) == (
        "B03", "EMERGENCY", "high", ["staff:priya"], 1, "open")
    assert a["text"].startswith("Bed 3 — possible heart emergency. Go now.")
    send = world.bus.actions("send_message", "A1")
    assert len(send) == 1 and send[0]["result"] == "screen_only" and "telegram off" in send[0]["detail"]
    assert any(l.get("event") == "note" and "telegram off" in l.get("msg", "") for l in world.log_lines())


def test_repeated_verdicts_do_not_duplicate(world):
    world.verdict("B03", "EMERGENCY", 1.0, n=5)
    assert len({a["alert_id"] for a in world.bus.alerts()}) == 1
    assert len(world.bus.alerts()) == 1
    assert len(world.bus.actions("send_message")) == 1


def test_ladder_timing_30s_steps(world):
    world.verdict("B03", "EMERGENCY", 1.0)
    aid = world.bus.alerts()[0]["alert_id"]
    world.advance(29.5)
    assert world.bus.alerts(aid)[-1]["ladder_step"] == 1
    world.advance(0.5)
    a = world.bus.alerts(aid)[-1]
    assert (a["ladder_step"], a["status"], a["to"]) == (2, "escalated", ["staff:priya", "staff:tom"])
    world.advance(29.5)
    assert world.bus.alerts(aid)[-1]["ladder_step"] == 2
    world.advance(0.5)
    a = world.bus.alerts(aid)[-1]
    assert a["ladder_step"] == 3 and set(a["to"]) == {"staff:priya", "staff:tom", "staff:dr_mehta"}
    world.advance(120)
    assert world.bus.alerts(aid)[-1]["ladder_step"] == 3
    esc = world.bus.actions("escalate")
    assert len(esc) == 2 and all(e["approved_by"] is None for e in esc)
    assert "no acknowledgement for 30 s" in esc[0]["detail"]


def test_ladder_step_setting(make_world):
    w = make_world(ladder_step_s=60)
    w.verdict("B03", "EMERGENCY", 1.0)
    w.advance(59)
    assert w.bus.alerts()[-1]["ladder_step"] == 1
    w.advance(1)
    assert w.bus.alerts()[-1]["ladder_step"] == 2


def test_ack_stops_ladder(world):
    world.verdict("B03", "EMERGENCY", 1.0)
    aid = world.bus.alerts()[0]["alert_id"]
    world.advance(20)
    world.request("ack_alert", aid, by="staff:tom", bed="B03")
    a = world.bus.alerts(aid)[-1]
    assert (a["status"], a["acked_by"], a["acked_ts"]) == ("acked", "staff:tom", world.clock.now_ms())
    world.advance(200)
    assert world.bus.alerts(aid)[-1]["ladder_step"] == 1
    assert world.bus.actions("escalate") == []
    ack = world.bus.actions("record_ack")[0]
    assert ack["approved_by"] == "staff:tom" and ack["undo_id"] == ack["action_id"] and "after 20.0 s" in ack["detail"]
    assert world.e.timers.get(f"ladder:{aid}") is None


def test_ack_of_unknown_alert_is_refused(world):
    world.request("ack_alert", "al_nothere")
    assert world.bus.actions() == []
    assert any(l.get("event") == "refused" for l in world.log_lines())


def test_escalate_request_moves_one_step_now(world):
    world.verdict("B03", "EMERGENCY", 1.0)
    aid = world.bus.alerts()[0]["alert_id"]
    world.advance(5)
    world.request("escalate_alert", aid, by="staff:priya")
    a = world.bus.alerts(aid)[-1]
    assert a["ladder_step"] == 2
    assert world.bus.actions("escalate")[0]["approved_by"] == "staff:priya"
    world.advance(29)
    assert world.bus.alerts(aid)[-1]["ladder_step"] == 2  # timer restarted from the escalation
    world.advance(1)
    assert world.bus.alerts(aid)[-1]["ladder_step"] == 3
    world.request("escalate_alert", aid, by="staff:priya")  # already at step 3
    assert any(l.get("event") == "refused" for l in world.log_lines())


def test_medium_needs_two_verdicts_and_single_blip_is_ignored(world):
    world.verdict("B05", "TAMPERING", 0.5)
    world.advance(5)
    world.verdict("B05", "NORMAL", 1.0)
    assert world.bus.alerts() == []
    world.verdict("B05", "TAMPERING", 0.5, n=2)
    a = world.bus.alerts()[-1]
    assert (a["verdict"], a["priority"], a["to"]) == ("TAMPERING", "medium", ["staff:priya"])
    assert a["text"].startswith("Bed 5 — monitor can't be trusted.")


def test_unsure_waits_six_verdicts_but_tampering_still_two(make_world):
    w = make_world(unsure_confirm_verdicts=6)
    w.verdict("B02", "UNSURE", 0.5, scores={"M3": 0.9}, n=5)
    assert w.bus.alerts() == []
    w.verdict("B02", "UNSURE", 0.5, scores={"M3": 0.9})
    assert w.bus.alerts()[-1]["verdict"] == "UNSURE"
    w.verdict("B05", "TAMPERING", 0.5, n=2)
    assert w.bus.alerts()[-1]["bed_id"] == "B05"


def test_table_priorities(world):
    beds = {"B01": "EMERGENCY", "B02": "BOTH", "B03": "TAMPERING", "B04": "DRIFTING", "B05": "LOOSE_SENSOR",
            "B06": "UNSURE", "B07": "NORMAL", "B08": "DEVICE_ATTACK"}
    want = {"EMERGENCY": "high", "BOTH": "high", "TAMPERING": "medium", "DRIFTING": "medium",
            "LOOSE_SENSOR": "low", "UNSURE": "medium"}
    for bed, verdict in beds.items():
        world.verdict(bed, verdict, 0.9, scores={"M4": 0.6} if verdict == "UNSURE" else None, n=2)
    got = {a["bed_id"]: (a["verdict"], a["priority"]) for a in world.bus.alerts()}
    assert {b: v for b, (v, _) in got.items()} == {b: v for b, v in beds.items() if v in want}
    assert all(p == want[v] for v, p in got.values())
    assert "B07" not in got and "B08" not in got  # NORMAL nobody, DEVICE_ATTACK IT only


def test_low_priority_has_no_ladder(world):
    world.verdict("B04", "LOOSE_SENSOR", 0.9, reasons=["PPG flat line"], n=2)
    a = world.bus.alerts()[-1]
    assert a["priority"] == "low" and "finger sensor loose" in a["text"] and "False alarm silenced" in a["text"]
    world.advance(120)
    assert world.bus.alerts()[-1]["ladder_step"] == 1


def test_warmup_unsure_is_not_alerted_but_offline_and_suspicious_are(world):
    v = world.verdict("B01", "UNSURE", 0.5, reasons=["Some checks are unavailable, warming up or inconclusive"],
                      scores={"M1": 0.1, "M2": None, "M3": None, "M4": 0.2, "M5": 0.1, "M6": None}, n=4)
    assert is_learning(v)
    assert world.bus.alerts() == []
    assert any("warming up" in l.get("msg", "") for l in world.log_lines())
    world.verdict("B02", "UNSURE", 1.0, reasons=["Monitor offline for at least 3 seconds; last values retained"], n=2)
    world.verdict("B12", "UNSURE", 0.5, scores={"M4": 0.6, "M5": 0.55}, n=2)
    assert {a["bed_id"] for a in world.bus.alerts()} == {"B02", "B12"}


def test_device_attack_is_it_only(world):
    world.verdict("B11", "DEVICE_ATTACK", 0.95, reasons=["Flood above 5 messages/s"], n=3)
    assert world.bus.alerts() == []
    it = [a for a in world.bus.actions("send_message", "A1") if a["device_id"] == "MON-11"]
    assert len(it) == 1 and "IT notified" in it[0]["detail"]


def test_both_keeps_nurse_alert_while_device_is_cut_off(world):
    world.verdict("B07", "BOTH", 0.95, reasons=["Monitor alarm remains active", "Replay"])
    a = world.bus.alerts()[-1]
    assert (a["verdict"], a["priority"], a["to"], a["status"]) == ("BOTH", "high", ["staff:tom"], "open")
    assert a["text"].startswith("Bed 7 — GO NOW. Do not trust the screen numbers.")
    assert world.bus.actions("disable_client", "A2")[0]["device_id"] == "MON-07"
    # the attack continues as TAMPERING (lower priority): the emergency alert is never lowered or closed
    world.verdict("B07", "TAMPERING", 0.95, n=7)
    a = world.bus.alerts()[-1]
    assert (a["verdict"], a["priority"], a["status"]) == ("BOTH", "high", "escalated")
    world.verdict("B07", "NORMAL", 1.0, n=3)
    assert world.bus.alerts()[-1]["status"] != "closed"  # unacked high alert stays until a person acks it
    world.request("ack_alert", a["alert_id"], by="staff:tom")
    world.verdict("B07", "NORMAL", 1.0, n=2)
    assert world.bus.alerts()[-1]["status"] == "closed"


def test_tampering_then_emergency_upgrades_same_alert(world):
    world.verdict("B07", "TAMPERING", 0.9, n=2)
    aid = world.bus.alerts()[-1]["alert_id"]
    world.verdict("B07", "BOTH", 0.95)
    a = world.bus.alerts()[-1]
    assert a["alert_id"] == aid and a["priority"] == "high" and a["verdict"] == "BOTH"
    assert world.bus.actions("edit_message", "A1")


def test_normal_closes_medium_alert(world):
    world.verdict("B08", "DRIFTING", 0.9, n=2)
    aid = world.bus.alerts()[-1]["alert_id"]
    world.verdict("B08", "NORMAL", 1.0)
    assert world.bus.alerts(aid)[-1]["status"] == "open"
    world.advance(5)
    world.verdict("B08", "NORMAL", 1.0)
    assert world.bus.alerts(aid)[-1]["status"] == "closed"
    world.verdict("B08", "DRIFTING", 0.9, n=2)
    assert world.bus.alerts()[-1]["alert_id"] != aid  # a new episode gets a new alert


# ---------------------------------------------------------------- UNSURE noise (ward run 2: 19 of 30 nurse alerts)
def _unsure(w, n, bed="B12"):
    w.verdict(bed, "UNSURE", 0.5, scores={"M4": 0.6}, n=n)


def test_unsure_alert_closes_only_after_4_normals(world):
    _unsure(world, 2)
    aid = world.bus.alerts()[-1]["alert_id"]
    world.advance(5)
    world.verdict("B12", "NORMAL", 1.0, n=3)
    assert world.bus.alerts(aid)[-1]["status"] == "open"
    world.advance(5)
    _unsure(world, 1)  # a 15 s NORMAL gap: still the same alert, no new page
    assert {a["alert_id"] for a in world.bus.alerts() if a["bed_id"] == "B12"} == {aid}
    assert len(world.bus.actions("send_message", "A1")) == 1
    world.advance(5)
    world.verdict("B12", "NORMAL", 1.0, n=4)
    assert world.bus.alerts(aid)[-1]["status"] == "closed"


def test_unsure_does_not_repage_same_nurse_within_3_min(world):
    _unsure(world, 2)
    first = world.bus.alerts()[-1]["alert_id"]
    world.advance(5)
    world.verdict("B12", "NORMAL", 1.0, n=4)  # closes at t
    assert world.bus.alerts(first)[-1]["status"] == "closed"
    sends = len(world.bus.actions("send_message", "A1"))
    world.advance(5)
    _unsure(world, 30)  # UNSURE again for 145 s: within 3 min of the close -> no new page
    assert len(world.bus.actions("send_message", "A1")) == sends
    assert [a for a in world.bus.alerts() if a["bed_id"] == "B12"][-1]["alert_id"] == first
    assert world.e.latest_verdict["B12"]["verdict"] == "UNSURE"  # the screen still shows the state
    notes = [l for l in world.log_lines() if l.get("event") == "note" and "no new page" in l.get("msg", "")]
    assert len(notes) == 1 and notes[0]["bed_id"] == "B12"
    _unsure(world, 8)  # past 180 s since the close: page again
    new = [a for a in world.bus.alerts() if a["bed_id"] == "B12"][-1]
    assert new["alert_id"] != first and new["status"] == "open"
    assert new["ts"] - world.bus.alerts(first)[-1]["ts"] >= 180_000


def test_unsure_cooldown_never_blocks_a_real_finding(world):
    _unsure(world, 2)
    world.advance(5)
    world.verdict("B12", "NORMAL", 1.0, n=4)
    world.advance(5)
    world.verdict("B12", "EMERGENCY", 1.0)
    assert [a for a in world.bus.alerts() if a["bed_id"] == "B12"][-1]["priority"] == "high"
    world.verdict("B11", "TAMPERING", 0.9, n=2)  # other beds unaffected
    assert [a for a in world.bus.alerts() if a["bed_id"] == "B11"]


def test_unsure_cooldown_other_nurse_is_paged(make_world):
    w = make_world()
    _unsure(w, 2)
    w.advance(5)
    w.verdict("B12", "NORMAL", 1.0, n=4)
    w.e.s.roster["B12"] = "staff:priya"  # shift change: a different nurse now owns the bed
    _unsure(w, 2)
    last = [a for a in w.bus.alerts() if a["bed_id"] == "B12"][-1]
    assert last["status"] == "open" and last["to"] == ["staff:priya"]


def test_unsure_settings(make_world):
    from sw_agents.config import Settings
    s = Settings.from_env({})
    assert (s.unsure_confirm_verdicts, s.unsure_clear_verdicts, s.unsure_repage_s) == (6, 4, 180)
    w = make_world(unsure_confirm_verdicts=6)
    _unsure(w, 5)
    assert w.bus.alerts() == []
    _unsure(w, 1)
    assert len(w.bus.alerts()) == 1


def test_same_priority_change_edits_not_duplicates(world):
    world.verdict("B05", "TAMPERING", 0.9, n=2)
    world.verdict("B05", "UNSURE", 0.6, scores={"M4": 0.6})
    alerts = world.bus.alerts()
    assert len({a["alert_id"] for a in alerts}) == 1 and alerts[-1]["verdict"] == "UNSURE"


def test_patient_not_ok_raises_high_alert_at_once(world):
    world.bedside("B02", "patient_not_ok", by="staff:priya")
    a = world.bus.alerts()[-1]
    assert (a["priority"], a["verdict"], a["bed_id"]) == ("high", "EMERGENCY", "B02")
    assert "patient NOT OK" in a["text"]
    # an acked lower alert is superseded by a new high one
    world.verdict("B05", "TAMPERING", 0.9, n=2)
    old = world.bus.alerts()[-1]["alert_id"]
    world.bedside("B05", "patient_ok", by="staff:priya")
    assert world.bus.alerts(old)[-1]["status"] == "acked"
    world.bedside("B05", "patient_not_ok", by="staff:priya")
    new = world.bus.alerts()[-1]
    assert new["alert_id"] != old and new["priority"] == "high" and new["status"] == "open"
    assert world.bus.alerts(old)[-1]["status"] == "closed"


def test_patient_ok_acks_hand_check(world):
    world.verdict("B05", "TAMPERING", 0.9, n=2)
    aid = world.bus.alerts()[-1]["alert_id"]
    world.bedside("B05", "patient_ok", by="staff:priya")
    a = world.bus.alerts(aid)[-1]
    assert a["status"] == "acked" and a["acked_by"] == "staff:priya"
    world.bedside("B05", "patient_ok", by="staff:priya")  # duplicate bedside message: ignored
    assert len(world.bus.actions("record_ack")) == 1


def test_undo_ack_reopens_and_restarts_ladder(world):
    world.verdict("B03", "EMERGENCY", 1.0)
    aid = world.bus.alerts()[0]["alert_id"]
    world.request("ack_alert", aid, by="staff:priya")
    ack = world.bus.actions("record_ack")[-1]
    world.advance(10)
    world.request("undo_action", ack["action_id"], by="staff:priya")
    undo = world.bus.actions("record_ack")[-1]
    assert undo["undoes"] == ack["action_id"] and undo["approved_by"] == "staff:priya" and undo["undo_id"] is None
    assert world.bus.alerts(aid)[-1]["status"] == "open" and world.bus.alerts(aid)[-1]["acked_by"] is None
    world.advance(30)
    assert world.bus.alerts(aid)[-1]["ladder_step"] == 2
    world.request("undo_action", ack["action_id"], by="staff:priya")  # double undo refused
    assert len(world.bus.actions("record_ack")) == 2
    assert any(l.get("reason") == "already undone" for l in world.log_lines())


def test_messages_are_not_undoable(world):
    world.verdict("B03", "EMERGENCY", 1.0)
    send = world.bus.actions("send_message")[0]
    assert send["undo_id"] is None
    world.request("undo_action", send["action_id"])
    assert any(l.get("reason") == "unknown or not undoable action" for l in world.log_lines())


def test_it_notice_needs_confidence_or_two_verdicts(world):
    world.verdict("B10", "TAMPERING", 0.6)
    assert not [a for a in world.bus.actions("send_message") if a["device_id"] == "MON-10"]
    world.advance(5)
    world.verdict("B10", "TAMPERING", 0.6)
    assert len([a for a in world.bus.actions("send_message") if a["device_id"] == "MON-10"]) == 1
