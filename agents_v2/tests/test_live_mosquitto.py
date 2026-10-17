"""Live test against a real Mosquitto (started here on a free port, stopped afterwards).

Run: SW_AGENTS_LIVE_MOSQUITTO=/opt/homebrew/sbin/mosquitto pytest -m live tests/test_live_mosquitto.py
"""
import os
import socket
import subprocess
import threading
import time

import pytest

from sw_common import Bus, make_demo_control, make_request, make_verdict, now_ms, window_start_for
from sw_agents.agents.a2_contain import DryRunBroker
from sw_agents.config import Settings
from sw_agents.service import Worker, build, subscriptions

MOSQUITTO = os.environ.get("SW_AGENTS_LIVE_MOSQUITTO")
pytestmark = [pytest.mark.live, pytest.mark.skipif(not MOSQUITTO, reason="set SW_AGENTS_LIVE_MOSQUITTO=<path to mosquitto>")]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def broker(tmp_path):
    port = free_port()
    conf = tmp_path / "mosquitto.conf"
    conf.write_text(f"listener {port} 127.0.0.1\nallow_anonymous true\npersistence false\n")
    proc = subprocess.Popen([MOSQUITTO, "-c", str(conf)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("mosquitto did not start")
    yield port
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def wait_for(pred, timeout=8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = pred()
        if found:
            return found
        time.sleep(0.05)
    return None


def test_live_end_to_end(broker, tmp_path):
    port = broker
    settings = Settings(state_dir=tmp_path / "state", ladder_step_s=1.5, mqtt_port=port, a2_confirm_s=1.0)
    seen: list[dict] = []
    lock = threading.Lock()

    def keep(msg, topic):
        with lock:
            seen.append(msg)

    def got(pred):
        with lock:
            return [m for m in seen if pred(m)]

    observer = Bus("127.0.0.1", port, "test-observer")
    observer.subscribe(["ward/alert", "ward/action", "ward/record"], keep)
    agents_bus = Bus("127.0.0.1", port, "sw-agents2-live")
    worker = Worker()
    engine = build(settings, agents_bus.publish, background=worker, broker=DryRunBroker())
    agents_bus.subscribe(subscriptions(settings), engine.handle)
    driver = Bus("127.0.0.1", port, "test-driver")
    stop = threading.Event()

    def ticker():
        while not stop.is_set():
            engine.tick()
            stop.wait(0.1)

    t = threading.Thread(target=ticker, daemon=True)
    try:
        assert observer.connect(5) and agents_bus.connect(5) and driver.connect(5)
        time.sleep(0.3)  # subscriptions settle
        t.start()

        def verdict(bed, v, conf):
            ts = now_ms()
            driver.publish(make_verdict(bed_id=bed, ts=ts, window_start=window_start_for(ts), verdict=v, confidence=conf,
                                        trust=0.1, last_trusted_ts=ts - 10_000, reasons=[f"{v} live"], scores={"M4": 0.9}))

        # EMERGENCY -> alert step 1 -> ladder step 2 -> ack via ward/request
        verdict("B03", "EMERGENCY", 1.0)
        alert = wait_for(lambda: got(lambda m: m["type"] == "alert" and m["bed_id"] == "B03"))
        assert alert and alert[0]["ladder_step"] == 1 and alert[0]["to"] == ["staff:priya"]
        aid = alert[0]["alert_id"]
        assert wait_for(lambda: got(lambda m: m["type"] == "alert" and m["alert_id"] == aid and m["ladder_step"] == 2))
        driver.publish(make_request(request_id="req_live1", by="staff:tom", action="ack_alert", target_id=aid, bed_id="B03"))
        acked = wait_for(lambda: got(lambda m: m["type"] == "alert" and m["alert_id"] == aid and m["status"] == "acked"))
        assert acked and acked[0]["acked_by"] == "staff:tom"

        # TAMPERING -> untrusted at once; held 1 s (a2_confirm_s) -> A2 dry-run cut-off + A3 incident + A5 report
        verdict("B05", "TAMPERING", 0.9)
        assert wait_for(lambda: got(lambda m: m["type"] == "action" and m["action"] == "set_bed_untrusted"))
        assert not got(lambda m: m["type"] == "action" and m["action"] == "disable_client")
        time.sleep(1.1)
        verdict("B05", "TAMPERING", 0.9)
        cut = wait_for(lambda: got(lambda m: m["type"] == "action" and m["action"] == "disable_client"))
        assert cut and cut[0]["result"] == "dry_run" and cut[0]["device_id"] == "MON-05"
        inc = wait_for(lambda: got(lambda m: m["type"] == "record" and m["kind"] == "incident"))
        assert inc and len(inc[0]["data"]["evidence"]) == 3
        assert wait_for(lambda: got(lambda m: m["type"] == "record" and m["kind"] == "report"))

        # undo through ward/request, then demo reset
        driver.publish(make_request(request_id="req_live2", by="staff:sam", action="undo_action",
                                    target_id=cut[0]["action_id"], bed_id="B05"))
        en = wait_for(lambda: got(lambda m: m["type"] == "action" and m["action"] == "enable_client"))
        assert en and en[0]["undoes"] == cut[0]["action_id"] and en[0]["approved_by"] == "staff:sam"
        driver.publish(make_demo_control(cmd="reset", run_id="run_live"))
        assert wait_for(lambda: engine.stats["resets"] == 1)
        assert engine.agents["A1"].current == {}
        assert engine.stats["invalid_outgoing"] == 0 and agents_bus.stats()["invalid"] == 0
    finally:
        stop.set()
        worker.stop()
        for b in (driver, agents_bus, observer):
            b.close()
