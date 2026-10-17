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
    assert len(en) == 1
    assert (en[0]["undoes"], en[0]["approved_by"], en[0]["device_id"], en[0]["result"]) == (
        cut["action_id"], "staff:sam", "MON-05", "ok")
    assert world.broker.calls == [("disable", "MON-05"), ("enable", "MON-05")]
    assert world.e.undone[cut["action_id"]] == world.e.undone[untrusted["action_id"]] == en[0]["action_id"]
    world.request("undo_action", untrusted["action_id"], by="staff:sam")  # both were undone together
    assert len(world.bus.actions("enable_client")) == 1
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
