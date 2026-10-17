"""A2: cut-off + untrusted, threshold, dry run, failure, undo, re-cut rule, isolate request, restart, security_v2."""
import os

import pytest

from sw_agents.agents.a2_contain import DryRunBroker, HubBroker, make_broker, valid_device
from sw_agents.config import Settings


def test_tampering_cuts_off_and_marks_untrusted(world):
    world.verdict("B05", "TAMPERING", 0.88)
    untrusted = world.bus.actions("set_bed_untrusted", "A2")
    cut = world.bus.actions("disable_client", "A2")
    assert len(untrusted) == 1 and len(cut) == 1
    assert (cut[0]["bed_id"], cut[0]["device_id"], cut[0]["result"]) == ("B05", "MON-05", "ok")
    assert cut[0]["undo_id"] == cut[0]["action_id"] and untrusted[0]["undo_id"] == untrusted[0]["action_id"]
    assert "session wiped" in cut[0]["detail"] and "conf 0.88" in cut[0]["detail"]
    assert world.broker.calls == [("disable", "MON-05")]
    world.verdict("B05", "TAMPERING", 0.9, n=5)
    assert len(world.bus.actions("disable_client")) == 1  # once per episode


@pytest.mark.parametrize("verdict", ["BOTH", "DEVICE_ATTACK"])
def test_other_triggers(world, verdict):
    world.verdict("B07", verdict, 0.95)
    assert world.broker.calls == [("disable", "MON-07")]


def test_below_threshold_or_other_verdicts_do_nothing(world):
    world.verdict("B05", "TAMPERING", 0.79)
    for v in ("EMERGENCY", "UNSURE", "DRIFTING", "LOOSE_SENSOR", "NORMAL"):
        world.verdict("B06", v, 0.99)
    assert world.broker.calls == [] and world.bus.actions(by="A2") == []


def test_threshold_setting(make_world):
    w = make_world(a2_min_confidence=0.5)
    w.verdict("B05", "TAMPERING", 0.6)
    assert w.broker.calls == [("disable", "MON-05")]


def test_dry_run_without_hub_options(make_world):
    w = make_world(broker="auto", dynsec_options=None)
    assert isinstance(w.a["A2"].broker, DryRunBroker)
    w.verdict("B05", "TAMPERING", 0.9)
    cut = w.bus.actions("disable_client")[0]
    assert cut["result"] == "dry_run" and cut["detail"].startswith("DRY RUN")
    w.request("undo_action", cut["action_id"], by="staff:sam")
    assert w.bus.actions("enable_client")[0]["result"] == "dry_run"


def test_force_dry_run_setting(tmp_path):
    s = Settings(state_dir=tmp_path, dynsec_options="/x/admin.conf", a2_force_dry_run=True)
    assert s.a2_dry_run and isinstance(make_broker(s), DryRunBroker)


def test_hub_failure_is_reported_honestly(world):
    world.broker.fail_disable = True
    world.verdict("B05", "TAMPERING", 0.9)
    cut = world.bus.actions("disable_client")[0]
    assert cut["result"] == "failed" and cut["undo_id"] is None and "FAILED" in cut["detail"]
    untrusted = world.bus.actions("set_bed_untrusted")[0]
    world.request("undo_action", untrusted["action_id"], by="staff:sam")
    en = world.bus.actions("enable_client")[0]
    assert en["result"] == "ok" and "had not been cut off" in en["detail"]
    assert world.broker.calls == [("disable", "MON-05")]  # nothing to re-enable


def test_undo_restores_and_person_decision_is_respected(world):
    world.verdict("B05", "TAMPERING", 0.9)
    cut = world.bus.actions("disable_client")[0]
    untrusted = world.bus.actions("set_bed_untrusted")[0]
    world.request("undo_action", cut["action_id"], by="staff:sam")
    en = world.bus.actions("enable_client")
    assert len(en) == 2  # one hub change; the pair is logged as undone
    assert (en[0]["undoes"], en[0]["approved_by"], en[0]["device_id"], en[0]["result"]) == (
        cut["action_id"], "staff:sam", "MON-05", "ok")
    assert en[1]["undoes"] == untrusted["action_id"] and "no second hub change" in en[1]["detail"]
    assert world.broker.calls == [("disable", "MON-05"), ("enable", "MON-05")]
    assert world.e.undone[cut["action_id"]] == en[0]["action_id"]
    assert world.e.undone[untrusted["action_id"]] == en[1]["action_id"]
    world.request("undo_action", untrusted["action_id"], by="staff:sam")  # both were undone together
    assert len(world.bus.actions("enable_client")) == 2
    # the attack verdict lingers: A2 does not override IT's decision
    world.verdict("B05", "TAMPERING", 0.95, n=3)
    assert len(world.bus.actions("disable_client")) == 1
    # a new episode after NORMAL is contained again
    world.verdict("B05", "NORMAL", 1.0)
    world.verdict("B05", "TAMPERING", 0.95)
    assert len(world.bus.actions("disable_client")) == 2


def test_failed_reenable_can_be_retried(world):
    world.verdict("B05", "TAMPERING", 0.9)
    cut = world.bus.actions("disable_client")[0]
    world.broker.fail_enable = True
    world.request("undo_action", cut["action_id"], by="staff:sam")
    assert world.bus.actions("enable_client")[0]["result"] == "failed"
    assert "MON-05" in world.a["A2"].contained
    world.broker.fail_enable = False
    world.request("undo_action", cut["action_id"], by="staff:sam")
    assert world.bus.actions("enable_client")[-1]["result"] == "ok"
    assert "MON-05" not in world.a["A2"].contained


def test_isolate_request(world):
    world.request("isolate_device", "MON-05", by="staff:sam", bed="B05")
    cut = world.bus.actions("disable_client")[0]
    assert cut["approved_by"] == "staff:sam" and world.broker.calls == [("disable", "MON-05")]
    world.request("isolate_device", "MON-05", by="staff:sam")
    assert len(world.bus.actions("disable_client")) == 1
    world.request("isolate_device", "MON-06", by="staff:sam", bed="B05")  # bed/device mismatch
    world.request("isolate_device", "MON-13", by="staff:sam")             # not in the ward
    assert world.broker.calls == [("disable", "MON-05")]
    reasons = [l.get("reason") for l in world.log_lines() if l.get("event") == "refused"]
    assert "device already cut off" in reasons and "bed and device do not belong together" in reasons
    assert "target is not MON-01..MON-12" in reasons


def test_device_id_validation():
    for good in ("MON-01", "MON-12"):
        assert valid_device(good) == good
    for bad in ("MON-13", "MON-00", "MON-5", "MON-05; rm -rf /", "mon-05", "MON-05\n", None, 5):
        with pytest.raises(ValueError):
            valid_device(bad)


def test_containment_survives_restart(make_world, tmp_path):
    w1 = make_world(state_dir=tmp_path / "s")
    w1.verdict("B05", "TAMPERING", 0.9)
    cut = w1.bus.actions("disable_client")[0]
    w2 = make_world(state_dir=tmp_path / "s")
    assert "MON-05" in w2.a["A2"].contained
    w2.request("undo_action", cut["action_id"], by="staff:sam")
    assert w2.bus.actions("enable_client")[0]["undoes"] == cut["action_id"]
    assert w2.broker.calls == [("enable", "MON-05")]


def test_hub_broker_uses_security_v2_argument_lists(tmp_path):
    options = tmp_path / "admin.conf"
    options.write_text("-h 127.0.0.1\n-p 8883\n")
    os.chmod(options, 0o600)
    calls = []

    class Done:
        def __init__(self, stdout=""):
            self.returncode, self.stdout, self.stderr = 0, stdout, ""

    state = {"disabled": "false"}

    def run(argv, **kw):
        calls.append((argv, kw))
        if argv[4] == "disableClient":
            state["disabled"] = "true"
        if argv[4] == "enableClient":
            state["disabled"] = "false"
        if argv[4] == "getClient":
            return Done(f"Username: {argv[5]}\nClientid: {argv[5]}\nDisabled: {state['disabled']}\n")
        return Done()

    hub = HubBroker(str(options), str(tmp_path / "audit.jsonl"))
    hub.helper.run = run
    hub.disable("MON-05")
    hub.enable("MON-05")
    assert calls[0][0] == ["mosquitto_ctrl", "-o", str(options), "dynsec", "disableClient", "MON-05"]
    assert all(kw["shell"] is False for _, kw in calls)
    assert [c[0][4] for c in calls] == ["disableClient", "getClient", "enableClient", "getClient"]
    with pytest.raises(ValueError):
        hub.disable("MON-05 MON-06")
    assert "password" not in (tmp_path / "audit.jsonl").read_text().lower()


# ---------------------------------------------------------------- sustained evidence before the hub cut-off
def _b(w, bed):
    return [a for a in w.bus.alerts() if a["bed_id"] == bed]


def test_tampering_waits_for_sustained_evidence_b05_flow(make_world):
    """doc12 B05: TAMPERING ~10:02 -> untrusted + hand-check at once, cut ~10:22, nurse OK 11:30, IT undo 15:30."""
    w = make_world(a2_confirm_s=20)
    t0 = w.clock.now_ms()
    w.verdict("B05", "TAMPERING", 0.9, n=4, every_s=5)  # 0, 5, 10, 15 s: not yet
    assert len(w.bus.actions("set_bed_untrusted", "A2")) == 1
    assert w.bus.actions("disable_client") == [] and w.broker.calls == []
    assert "still connected" in w.a["A2"].state_text("MON-05")
    assert _b(w, "B05")[-1]["text"].startswith("Bed 5 — monitor can't be trusted.")  # nurse told at once
    w.verdict("B05", "TAMPERING", 0.9, n=2, every_s=5)  # 20 s held (the 2nd one is at +20 s) -> cut
    cut = w.bus.actions("disable_client")
    assert len(cut) == 1 and w.broker.calls == [("disable", "MON-05")]
    assert cut[0]["ts"] - t0 == 20_000 and "held 20 s" in cut[0]["detail"]
    assert cut[0]["undo_id"] == cut[0]["action_id"]
    assert any("after MON-05 was cut off" in a["detail"] for a in w.bus.actions("list_devices"))
    w.verdict("B05", "TAMPERING", 0.9, n=3)
    assert len(w.bus.actions("disable_client")) == 1
    w.bedside("B05", "patient_ok")
    assert "MON-05" in w.a["A2"].contained
    w.request("undo_action", cut[0]["action_id"], by="staff:sam")
    assert "MON-05" not in w.a["A2"].contained and w.broker.calls[-1] == ("enable", "MON-05")


def test_both_after_tampering_cuts_at_once_and_high_alert_stays_b07(make_world):
    """doc12 B07: TAMPERING 13:47, real VFIB alarm reaches the brain at 14:00, BOTH 14:02 -> high alert + cut."""
    w = make_world(a2_confirm_s=20)
    w.verdict("B07", "TAMPERING", 0.95, n=3, every_s=5)  # 13:47, 13:52, 13:57 (10 s held)
    assert w.broker.calls == [] and "MON-07" in w.a["A2"].contained  # untrusted, still connected
    w.advance(5)
    w.verdict("B07", "BOTH", 0.95, reasons=["Monitor alarm remains active", "Forged loop"])  # 14:02
    assert w.broker.calls == [("disable", "MON-07")]
    assert "BOTH" in w.bus.actions("disable_client")[0]["detail"]
    high = _b(w, "B07")[-1]
    assert high["priority"] == "high" and high["verdict"] == "BOTH"
    w.verdict("B07", "UNSURE", 0.6, reasons=["Monitor offline"], n=6)  # cut off: brain sees silence
    w.verdict("B07", "TAMPERING", 0.95, n=4)
    last = _b(w, "B07")[-1]
    assert last["alert_id"] == high["alert_id"] and last["priority"] == "high" and last["status"] != "closed"
    assert len(w.bus.actions("disable_client")) == 1


def test_both_first_cuts_at_once(make_world):
    w = make_world(a2_confirm_s=20)
    w.verdict("B06", "BOTH", 0.95)
    assert len(w.bus.actions("set_bed_untrusted")) == 1 and w.broker.calls == [("disable", "MON-06")]


def test_tampering_blip_shorter_than_confirm_never_cuts(make_world):
    w = make_world(a2_confirm_s=20)
    w.verdict("B05", "TAMPERING", 0.9, n=4, every_s=5)  # 15 s
    w.advance(5)
    w.verdict("B05", "NORMAL", 1.0)  # run broken
    w.advance(5)
    w.verdict("B05", "TAMPERING", 0.9, n=4, every_s=5)  # another 15 s: the count restarted
    w.advance(5)
    w.verdict("B05", "UNSURE", 0.6)  # a non-attack verdict also breaks the run
    w.advance(5)
    w.verdict("B05", "TAMPERING", 0.9, n=2, every_s=5)
    w.verdict("B05", "TAMPERING", 0.5, n=4, every_s=5)  # below the confidence threshold: not evidence
    assert w.broker.calls == [] and w.bus.actions("disable_client") == []
    assert len(w.bus.actions("set_bed_untrusted")) == 1  # bed stays untrusted until a person decides
    untrusted = w.bus.actions("set_bed_untrusted")[0]
    w.request("undo_action", untrusted["action_id"], by="staff:sam")
    en = w.bus.actions("enable_client")
    assert len(en) == 1 and "had not been cut off" in en[0]["detail"] and w.broker.calls == []
    w.verdict("B05", "TAMPERING", 0.9, n=6)  # IT trusted it again: A2 does not override them
    assert w.broker.calls == []


def test_person_isolate_cuts_a_waiting_device_now(make_world):
    w = make_world(a2_confirm_s=20)
    w.verdict("B05", "TAMPERING", 0.9)
    w.request("isolate_device", "MON-05", by="staff:sam", bed="B05")
    cut = w.bus.actions("disable_client")
    assert len(cut) == 1 and cut[0]["approved_by"] == "staff:sam" and w.broker.calls == [("disable", "MON-05")]
    assert len(w.bus.actions("set_bed_untrusted")) == 1


def test_reset_releases_a_waiting_bed_and_forgets_the_run(make_world):
    w = make_world(a2_confirm_s=20)
    w.verdict("B05", "TAMPERING", 0.9, n=3)
    w.demo("reset")
    assert w.a["A2"].contained == {} and w.broker.calls == []
    w.verdict("B05", "TAMPERING", 0.9, n=4)  # 15 s since reset: not 25
    assert w.broker.calls == []


def test_confirm_setting_from_env():
    assert Settings.from_env({}).a2_confirm_s == 20
    assert Settings.from_env({"SW_A2_CONFIRM_S": "0"}).a2_confirm_s == 0
