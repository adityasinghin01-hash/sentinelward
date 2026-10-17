"""Bus: a small, validated publish/subscribe wrapper around paho-mqtt 2.x (CallbackAPIVersion.VERSION2).

paho is imported only when a Bus is created, so the rest of sw_common works without it.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Callable, Iterable

from .messages import decode, encode
from .topics import check_pattern, parse_topic, qos_retain_for, topic_for, topic_matches

Handler = Callable[[dict, str], None]
ClientFactory = Callable[[str], Any]

_SUBSCRIBE_QOS = 1  # QoS 0 vitals still arrive at QoS 0; everything else keeps its QoS 1
_MAX_LOGGED_TOPICS = 10_000  # bounds the "logged once per topic" memory
_ERR_SUCCESS = 0  # paho MQTT_ERR_SUCCESS
_ERR_NO_CONN = 4  # paho MQTT_ERR_NO_CONN


def _paho_client(client_id: str) -> Any:
    try:
        from paho.mqtt import client as mqtt
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise ImportError("sw_common.Bus needs paho-mqtt>=2.1: pip install 'paho-mqtt>=2.1'") from exc
    return mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)


def _is_failure(reason_code: Any) -> bool:
    # paho passes a ReasonCode (with .is_failure); fakes and MQTT 3.1.1 paths may pass an int.
    flag = getattr(reason_code, "is_failure", None)
    if flag is not None:
        return bool(flag)
    return reason_code != 0


class Bus:
    """Validated MQTT client: publish() picks topic/QoS/retain, subscribe() delivers only valid messages.

    Runs paho's network loop in a background thread and reconnects by itself with backoff.
    """

    def __init__(self, host: str, port: int, client_id: str, *, username: str | None = None,
                 password: str | None = None, tls_ca_file: str | None = None, keepalive: int = 30,
                 min_backoff_s: int = 1, max_backoff_s: int = 30, strict: bool = False,
                 logger: logging.Logger | None = None,
                 client_factory: ClientFactory | None = None) -> None:
        """Create the client; nothing touches the network until connect().

        username/password and tls_ca_file are off by default (use port 8883 with TLS).
        """
        if type(host) is not str or not host:
            raise ValueError(f"Bus: host must be a non-empty string, got {host!r}")
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError(f"Bus: port must be an int from 1 to 65535, got {port!r}")
        if type(client_id) is not str or not client_id:
            raise ValueError(f"Bus: client_id must be a non-empty string, got {client_id!r}")
        if password is not None and username is None:
            raise ValueError("Bus: password given without username")
        if username is not None and (type(username) is not str or not username):
            raise ValueError(f"Bus: username must be a non-empty string, got {username!r}")
        if tls_ca_file is not None and not os.path.isfile(tls_ca_file):
            raise FileNotFoundError(f"Bus: tls_ca_file {tls_ca_file!r} does not exist")
        if type(keepalive) is not int or keepalive < 5:
            raise ValueError(f"Bus: keepalive must be an int >= 5 seconds, got {keepalive!r}")
        if type(min_backoff_s) is not int or type(max_backoff_s) is not int or not 1 <= min_backoff_s <= max_backoff_s:
            raise ValueError(f"Bus: need integers 1 <= min_backoff_s <= max_backoff_s, got {min_backoff_s!r}, {max_backoff_s!r}")

        self._host = host
        self._port = port
        self._keepalive = keepalive
        self._strict = strict
        self._log = logger or logging.getLogger("sw_common.bus")
        self._lock = threading.Lock()
        self._connected = threading.Event()
        self._handlers: list[tuple[str, Handler]] = []
        self._patterns: list[str] = []
        self._logged_topics: set[str] = set()
        self._ever_connected = False
        self._started = False
        self._closed = False
        self._stats = {"sent": 0, "queued": 0, "dropped": 0, "received": 0, "invalid": 0,
                       "reconnects": 0, "handler_errors": 0}

        self._client = (client_factory or _paho_client)(client_id)
        if username is not None:
            self._client.username_pw_set(username, password)
        if tls_ca_file is not None:
            self._client.tls_set(ca_certs=tls_ca_file)
        self._client.reconnect_delay_set(min_delay=min_backoff_s, max_delay=max_backoff_s)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

    # ------------------------------------------------------------------ lifecycle

    def connect(self, wait_s: float = 5.0) -> bool:
        """Start the background loop and connect; return True if connected within wait_s.

        If the hub is down, paho keeps retrying in the background (with backoff) either way.
        """
        if self._closed:
            raise RuntimeError("Bus: connect() after close()")
        if not self._started:
            self._client.connect_async(self._host, self._port, keepalive=self._keepalive)
            self._client.loop_start()
            self._started = True
        return self._connected.wait(wait_s) if wait_s > 0 else self._connected.is_set()

    def close(self) -> None:
        """Disconnect cleanly and stop the background thread; safe to call twice."""
        if self._closed:
            return
        self._closed = True
        if self._started:
            try:
                self._client.disconnect()
            finally:
                self._client.loop_stop()
        self._connected.clear()

    def __enter__(self) -> "Bus":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    @property
    def is_connected(self) -> bool:
        """True while the hub connection is up."""
        return self._connected.is_set()

    def stats(self) -> dict[str, int]:
        """Return a copy of the counters: sent, queued, dropped, received, invalid, reconnects, handler_errors."""
        with self._lock:
            return dict(self._stats)

    # ------------------------------------------------------------------ publish / subscribe

    def publish(self, message: dict) -> bool:
        """Check the message, then publish it on its own topic with its QoS and retain flag.

        Raises MessageError if invalid. Returns False only if the message was dropped
        (QoS 0 while disconnected); QoS 1 messages are queued by paho until reconnect.
        """
        payload = encode(message, strict=self._strict)  # raises MessageError
        topic = topic_for(message)
        qos, retain = qos_retain_for(message["type"])
        info = self._client.publish(topic, payload, qos=qos, retain=retain)
        rc = getattr(info, "rc", info)
        with self._lock:
            if rc == _ERR_SUCCESS:
                self._stats["sent"] += 1
            elif rc == _ERR_NO_CONN and qos > 0:
                self._stats["queued"] += 1
            else:
                self._stats["dropped"] += 1
        if rc == _ERR_SUCCESS or (rc == _ERR_NO_CONN and qos > 0):
            return True
        self._log.debug("dropped %s message on %s (paho rc=%s)", message["type"], topic, rc)
        return False

    def subscribe(self, pattern: str | Iterable[str], handler: Handler) -> None:
        """Call handler(message, topic) for every valid message on pattern (a filter or a list of them)."""
        patterns = [pattern] if isinstance(pattern, str) else list(pattern)
        if not patterns:
            raise ValueError("Bus.subscribe: no pattern given")
        for p in patterns:
            check_pattern(p)
        if not callable(handler):
            raise TypeError(f"Bus.subscribe: handler must be callable, got {type(handler).__name__}")
        new: list[str] = []
        with self._lock:
            for p in patterns:
                self._handlers.append((p, handler))
                if p not in self._patterns:
                    self._patterns.append(p)
                    new.append(p)
        if self._connected.is_set():
            for p in new:
                self._client.subscribe(p, qos=_SUBSCRIBE_QOS)

    # ------------------------------------------------------------------ paho callbacks (network thread)

    def _on_connect(self, client: Any, userdata: Any, flags: Any, reason_code: Any,
                    properties: Any = None) -> None:
        if _is_failure(reason_code):
            self._log.error("MQTT connect to %s:%s refused: %s", self._host, self._port, reason_code)
            return
        with self._lock:
            if self._ever_connected:
                self._stats["reconnects"] += 1
            self._ever_connected = True
            patterns = list(self._patterns)
        self._connected.set()
        self._log.info("MQTT connected to %s:%s", self._host, self._port)
        for p in patterns:  # clean sessions forget subscriptions, so renew them on every connect
            client.subscribe(p, qos=_SUBSCRIBE_QOS)

    def _on_disconnect(self, client: Any, userdata: Any, flags: Any, reason_code: Any,
                       properties: Any = None) -> None:
        self._connected.clear()
        if not self._closed:
            self._log.warning("MQTT disconnected from %s:%s (%s); reconnecting", self._host, self._port, reason_code)

    def _on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        topic = msg.topic
        with self._lock:
            self._stats["received"] += 1
        if not msg.payload:
            # A zero-length payload is MQTT's "clear retained message" signal, not a message.
            return
        message, errors = decode(msg.payload, strict=self._strict)
        if not errors:
            errors = _topic_mismatch(topic, message)  # type: ignore[arg-type]
        if errors:
            self._note_invalid(topic, errors)
            return
        with self._lock:
            handlers = [h for p, h in self._handlers if topic_matches(p, topic)]
        for handler in handlers:
            try:
                handler(message, topic)  # type: ignore[arg-type]
            except Exception:
                with self._lock:
                    self._stats["handler_errors"] += 1
                self._log.exception("handler %r raised on %s", handler, topic)

    def _note_invalid(self, topic: str, errors: list[str]) -> None:
        with self._lock:
            self._stats["invalid"] += 1
            first = topic not in self._logged_topics and len(self._logged_topics) < _MAX_LOGGED_TOPICS
            if first:
                self._logged_topics.add(topic)
        if first:
            self._log.warning("invalid message on %s: %s (further invalid messages on this topic are only counted)",
                              topic, "; ".join(errors[:5]))


def _topic_mismatch(topic: str, message: dict) -> list[str]:
    """Errors if the topic does not fit the message type and IDs inside it."""
    try:
        parsed = parse_topic(topic)
    except ValueError as exc:
        return [f"topic: {exc}"]
    mtype = message["type"]
    errs: list[str] = []
    if parsed.kind != mtype:
        errs.append(f"topic: {topic!r} carries {parsed.kind} messages, got type {mtype!r}")
        return errs
    for field in ("bed_id", "model", "device_id"):
        want = getattr(parsed, field)
        if want is not None and message.get(field) != want:
            errs.append(f"{mtype}.{field}: {message.get(field)!r} does not match topic {topic!r}")
    return errs


__all__ = ["Bus", "Handler"]
