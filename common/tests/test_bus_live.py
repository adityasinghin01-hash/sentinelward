"""Optional end-to-end test against a real MQTT broker (e.g. Mosquitto).

Runs only when MQTT_TEST_HOST is set. Optional: MQTT_TEST_PORT (default 1883),
MQTT_TEST_USERNAME, MQTT_TEST_PASSWORD, MQTT_TEST_CA_FILE.
"""

from __future__ import annotations

import os
import threading
import uuid

import pytest

from conftest import EXAMPLES
from sw_common import Bus, verdict_topic, vitals_topic

HOST = os.environ.get("MQTT_TEST_HOST")

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not HOST, reason="set MQTT_TEST_HOST to run against a real broker"),
]


def make_bus(name: str) -> Bus:
    pytest.importorskip("paho.mqtt")
    return Bus(
        HOST or "localhost",
        int(os.environ.get("MQTT_TEST_PORT", "1883")),
        f"sw-common-test-{name}-{uuid.uuid4().hex[:8]}",
        username=os.environ.get("MQTT_TEST_USERNAME") or None,
        password=os.environ.get("MQTT_TEST_PASSWORD") or None,
        tls_ca_file=os.environ.get("MQTT_TEST_CA_FILE") or None,
    )


def test_publish_and_receive_through_real_broker():
    bed = "B12"
    verdict = {**EXAMPLES["verdict"], "bed_id": bed}
    vitals = {**EXAMPLES["vitals"], "bed_id": bed, "device_id": "MON-12"}
    got: dict[str, dict] = {}
    done = threading.Event()

    def on_message(message: dict, topic: str) -> None:
        got[message["type"]] = message
        if len(got) == 2:
            done.set()

    sub, pub = make_bus("sub"), make_bus("pub")
    try:
        sub.subscribe([verdict_topic(bed), vitals_topic(bed)], on_message)
        assert sub.connect(wait_s=10), "subscriber could not connect"
        assert pub.connect(wait_s=10), "publisher could not connect"
        pub._client.publish(vitals_topic(bed), b"garbage", qos=1)  # raw bytes, bypassing the checks
        assert pub.publish(verdict)
        assert pub.publish(vitals)
        assert done.wait(10), f"only received {sorted(got)}"
        assert got["verdict"] == verdict and got["vitals"] == vitals

        # The verdict is retained: a new subscriber gets it straight away.
        retained = threading.Event()
        late = make_bus("late")
        late.subscribe(verdict_topic(bed), lambda m, t: retained.set())
        try:
            assert late.connect(wait_s=10)
            assert retained.wait(10), "retained verdict not delivered"
        finally:
            late.close()

        assert sub.stats()["invalid"] >= 1
        assert pub.stats()["sent"] == 2
    finally:
        pub._client.publish(verdict_topic(bed), b"", qos=1, retain=True)  # clear the retained test verdict
        pub.close()
        sub.close()
