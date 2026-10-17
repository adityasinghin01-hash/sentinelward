"""Tests for sw_common.bus.Bus against a fake paho client (no broker, no network)."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any

import pytest

from conftest import EXAMPLES
from sw_common import Bus, MessageError, VERDICT_SUB, VITALS_SUB, encode, verdict_topic, vitals_topic

NO_CONN = 4  # paho MQTT_ERR_NO_CONN


class FakeClient:
    """Records what Bus asks paho to do; tests drive the callbacks by hand."""

    def __init__(self, client_id: str) -> None:
        self.client_id = client_id
        self.published: list[tuple[str, bytes, int, bool]] = []
        self.subscribed: list[tuple[str, int]] = []
        self.auth: tuple[str, str | None] | None = None
        self.tls_ca: str | None = None
        self.delays: tuple[int, int] | None = None
        self.connect_args: tuple[str, int, int] | None = None
        self.loop_running = False
        self.disconnects = 0
        self.publish_rc = 0
        self.on_connect: Any = None
        self.on_disconnect: Any = None
        self.on_message: Any = None

    def username_pw_set(self, username: str, password: str | None = None) -> None:
        self.auth = (username, password)

    def tls_set(self, ca_certs: str | None = None) -> None:
        self.tls_ca = ca_certs

    def reconnect_delay_set(self, min_delay: int = 1, max_delay: int = 120) -> None:
        self.delays = (min_delay, max_delay)

    def connect_async(self, host: str, port: int = 1883, keepalive: int = 60) -> None:
        self.connect_args = (host, port, keepalive)

    def loop_start(self) -> None:
        self.loop_running = True
        self.fire_connect()

    def loop_stop(self) -> None:
        self.loop_running = False

    def disconnect(self) -> None:
        self.disconnects += 1
        self.on_disconnect(self, None, {}, 0, None)

    def publish(self, topic: str, payload: bytes, qos: int = 0, retain: bool = False) -> SimpleNamespace:
        self.published.append((topic, payload, qos, retain))
        return SimpleNamespace(rc=self.publish_rc)

    def subscribe(self, topic: str, qos: int = 0) -> tuple[int, int]:
        self.subscribed.append((topic, qos))
        return (0, len(self.subscribed))

    # test helpers -----------------------------------------------------------
    def fire_connect(self, rc: int = 0) -> None:
        self.on_connect(self, None, {}, rc, None)

    def fire_disconnect(self, rc: int = 7) -> None:
        self.on_disconnect(self, None, {}, rc, None)

    def deliver(self, topic: str, payload: bytes) -> None:
        self.on_message(self, None, SimpleNamespace(topic=topic, payload=payload))


@pytest.fixture
def fake() -> dict[str, FakeClient]:
    return {}


@pytest.fixture
def bus(fake):
    def factory(client_id: str) -> FakeClient:
        fake["client"] = FakeClient(client_id)
        return fake["client"]

    b = Bus("hub.local", 1883, "test-client", client_factory=factory)
    assert b.connect(wait_s=0.1) is True
    yield b
    b.close()


def client(fake) -> FakeClient:
    return fake["client"]


# --------------------------------------------------------------------------- publish

@pytest.mark.parametrize("mtype,topic,qos,retain", [
    ("vitals", "ward/bed/B03/vitals", 0, False),
    ("score", "ward/bed/B03/score/M3", 1, False),
    ("verdict", "ward/bed/B07/verdict", 1, True),
    ("action", "ward/action", 1, False),
    ("alert", "ward/alert", 1, False),
    ("bedside_check", "ward/bed/B07/bedside", 1, False),
    ("net_features", "net/device/MON-07/features", 1, False),
    ("request", "ward/request", 1, False),
    ("demo_control", "ward/demo/control", 1, False),
    ("record", "ward/record", 1, False),
])
def test_publish_picks_topic_qos_and_retain(bus, fake, mtype, topic, qos, retain):
    assert bus.publish(EXAMPLES[mtype]) is True
    (got_topic, payload, got_qos, got_retain), = client(fake).published
    assert (got_topic, got_qos, got_retain) == (topic, qos, retain)
    assert json.loads(payload) == EXAMPLES[mtype]
    assert bus.stats()["sent"] == 1


def test_publish_refuses_invalid_message(bus, fake):
    bad = {**EXAMPLES["verdict"], "priority": "high"}
    with pytest.raises(MessageError, match="verdict.priority"):
        bus.publish(bad)
    assert client(fake).published == []
    assert bus.stats()["sent"] == 0


def test_publish_cleans_nan(bus, fake):
    msg = {**EXAMPLES["vitals"], "hr": float("nan")}
    bus.publish(msg)
    assert json.loads(client(fake).published[0][1])["hr"] is None


def test_publish_while_disconnected(bus, fake):
    client(fake).publish_rc = NO_CONN
    assert bus.publish(EXAMPLES["vitals"]) is False  # QoS 0 is dropped
    assert bus.publish(EXAMPLES["alert"]) is True  # QoS 1 is queued by paho
    stats = bus.stats()
    assert (stats["sent"], stats["dropped"], stats["queued"]) == (0, 1, 1)


def test_strict_bus_refuses_unknown_fields(fake):
    b = Bus("h", 1883, "c", strict=True, client_factory=lambda cid: fake.setdefault("client", FakeClient(cid)))
    with pytest.raises(MessageError, match="unknown field"):
        b.publish({**EXAMPLES["alert"], "channel": "sms"})


# --------------------------------------------------------------------------- subscribe / receive

def test_valid_message_reaches_handler(bus, fake):
    got: list[tuple[dict, str]] = []
    bus.subscribe(VERDICT_SUB, lambda m, t: got.append((m, t)))
    assert (VERDICT_SUB, 1) in client(fake).subscribed
    client(fake).deliver(verdict_topic("B07"), encode(EXAMPLES["verdict"]))
    assert got == [(EXAMPLES["verdict"], "ward/bed/B07/verdict")]
    assert bus.stats()["received"] == 1 and bus.stats()["invalid"] == 0


def test_invalid_message_is_counted_not_raised_and_logged_once(bus, fake, caplog):
    got: list[Any] = []
    bus.subscribe(VITALS_SUB, lambda m, t: got.append(m))
    topic = vitals_topic("B03")
    with caplog.at_level(logging.WARNING, logger="sw_common.bus"):
        client(fake).deliver(topic, b"\xff not json")
        client(fake).deliver(topic, json.dumps({**EXAMPLES["vitals"], "ecg": [0] * 124}).encode())
        client(fake).deliver(vitals_topic("B04"), b"{}")
    assert got == []
    assert bus.stats()["invalid"] == 3 and bus.stats()["received"] == 3
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "invalid message" in r.getMessage()]
    assert len(warnings) == 2  # once for B03, once for B04
    assert topic in warnings[0].getMessage()


def test_topic_body_mismatch_is_invalid(bus, fake):
    got: list[Any] = []
    bus.subscribe("ward/#", lambda m, t: got.append(m))
    client(fake).deliver(vitals_topic("B04"), encode(EXAMPLES["vitals"]))  # body says B03
    client(fake).deliver("ward/alert", encode(EXAMPLES["action"]))  # wrong type for topic
    client(fake).deliver("ward/unknown", encode(EXAMPLES["action"]))  # not a contract topic
    assert got == [] and bus.stats()["invalid"] == 3


def test_handlers_only_get_matching_topics(bus, fake):
    vitals, verdicts = [], []
    bus.subscribe(VITALS_SUB, lambda m, t: vitals.append(t))
    bus.subscribe([VERDICT_SUB, "ward/action"], lambda m, t: verdicts.append(t))
    client(fake).deliver("ward/bed/B03/vitals", encode(EXAMPLES["vitals"]))
    client(fake).deliver("ward/bed/B07/verdict", encode(EXAMPLES["verdict"]))
    client(fake).deliver("ward/action", encode(EXAMPLES["action"]))
    assert vitals == ["ward/bed/B03/vitals"]
    assert verdicts == ["ward/bed/B07/verdict", "ward/action"]


def test_handler_exception_does_not_escape(bus, fake, caplog):
    def boom(m: dict, t: str) -> None:
        raise RuntimeError("handler bug")

    bus.subscribe("ward/action", boom)
    with caplog.at_level(logging.ERROR, logger="sw_common.bus"):
        client(fake).deliver("ward/action", encode(EXAMPLES["action"]))
    assert bus.stats()["handler_errors"] == 1
    assert any("raised on ward/action" in r.getMessage() for r in caplog.records)


def test_empty_payload_is_ignored(bus, fake):
    got: list[Any] = []
    bus.subscribe(VERDICT_SUB, lambda m, t: got.append(m))
    client(fake).deliver("ward/bed/B07/verdict", b"")
    assert got == [] and bus.stats()["invalid"] == 0


def test_subscribe_rejects_bad_input(bus):
    with pytest.raises(ValueError):
        bus.subscribe("ward/#/x", lambda m, t: None)
    with pytest.raises(ValueError):
        bus.subscribe([], lambda m, t: None)
    with pytest.raises(TypeError):
        bus.subscribe("ward/action", "not callable")  # type: ignore[arg-type]


# --------------------------------------------------------------------------- connection

def test_reconnect_counts_and_resubscribes(bus, fake):
    bus.subscribe(VERDICT_SUB, lambda m, t: None)
    c = client(fake)
    c.subscribed.clear()
    c.fire_disconnect()
    assert bus.is_connected is False
    c.fire_connect()
    assert bus.is_connected is True
    assert bus.stats()["reconnects"] == 1
    assert c.subscribed == [(VERDICT_SUB, 1)]


def test_subscriptions_made_before_connect_are_sent_on_connect(fake):
    b = Bus("h", 1883, "c", client_factory=lambda cid: fake.setdefault("client", FakeClient(cid)))
    b.subscribe(VITALS_SUB, lambda m, t: None)
    assert client(fake).subscribed == []
    b.connect(wait_s=0.1)
    assert client(fake).subscribed == [(VITALS_SUB, 1)]
    assert b.stats()["reconnects"] == 0
    b.close()


def test_refused_connection_is_not_connected(fake, caplog):
    class Refusing(FakeClient):
        def loop_start(self) -> None:
            self.loop_running = True
            self.fire_connect(rc=135)  # MQTT v5 "not authorized"

    b = Bus("h", 1883, "c", client_factory=lambda cid: fake.setdefault("client", Refusing(cid)))
    with caplog.at_level(logging.ERROR, logger="sw_common.bus"):
        assert b.connect(wait_s=0.05) is False
    assert any("refused" in r.getMessage() for r in caplog.records)
    b.close()


def test_connection_settings_passed_to_paho(fake, tmp_path):
    ca = tmp_path / "ca.pem"
    ca.write_text("dummy")
    b = Bus("hub.local", 8883, "cid-7", username="agent-a2", password="secret", tls_ca_file=str(ca),
            keepalive=20, min_backoff_s=2, max_backoff_s=60,
            client_factory=lambda cid: fake.setdefault("client", FakeClient(cid)))
    c = client(fake)
    assert c.client_id == "cid-7"
    assert c.auth == ("agent-a2", "secret")
    assert c.tls_ca == str(ca)
    assert c.delays == (2, 60)
    b.connect(wait_s=0.1)
    assert c.connect_args == ("hub.local", 8883, 20)
    b.close()


def test_auth_and_tls_off_by_default(bus, fake):
    assert client(fake).auth is None and client(fake).tls_ca is None


@pytest.mark.parametrize("kwargs,exc", [
    ({"host": ""}, ValueError),
    ({"port": 0}, ValueError),
    ({"port": "1883"}, ValueError),
    ({"client_id": ""}, ValueError),
    ({"password": "x"}, ValueError),
    ({"username": ""}, ValueError),
    ({"tls_ca_file": "/no/such/ca.pem"}, FileNotFoundError),
    ({"min_backoff_s": 10, "max_backoff_s": 5}, ValueError),
    ({"keepalive": 1}, ValueError),
])
def test_bad_settings_rejected(kwargs, exc):
    args = {"host": "h", "port": 1883, "client_id": "c", **kwargs}
    with pytest.raises(exc):
        Bus(args.pop("host"), args.pop("port"), args.pop("client_id"), client_factory=FakeClient, **args)


def test_close_is_clean_and_idempotent(fake):
    b = Bus("h", 1883, "c", client_factory=lambda cid: fake.setdefault("client", FakeClient(cid)))
    with b:
        b.connect(wait_s=0.1)
        assert client(fake).loop_running
    assert client(fake).loop_running is False and client(fake).disconnects == 1
    b.close()
    assert client(fake).disconnects == 1
    with pytest.raises(RuntimeError):
        b.connect()


def test_default_factory_builds_real_paho_client():
    pytest.importorskip("paho.mqtt")
    from paho.mqtt import client as mqtt

    b = Bus("localhost", 1883, "sw-common-unit")
    assert isinstance(b._client, mqtt.Client)  # constructed only; never connected
    b.close()
