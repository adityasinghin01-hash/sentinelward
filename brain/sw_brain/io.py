"""Shared contract boundary; bounded receipts keep inference off the MQTT thread."""
from __future__ import annotations
from dataclasses import dataclass
import logging
import math
import os
import queue
import re
import threading
import time
from typing import Protocol

import sw_common
from sw_common.topics import topic_for, topic_matches

WARD_MAX_BED = len(sw_common.BED_IDS)  # 12: the ward's B01-B12
CONTRACT_MAX_BED = 99                  # sw_common accepts two-digit IDs B01-B99 / MON-01-MON-99


def max_bed_from_env(environ=None):
    """SW_BRAIN_MAX_BED (default 12): highest accepted bed number, 1..99."""
    raw = (os.environ if environ is None else environ).get('SW_BRAIN_MAX_BED', '').strip()
    if not raw:
        return WARD_MAX_BED
    if not raw.isdigit() or not 1 <= int(raw) <= CONTRACT_MAX_BED:
        raise ValueError(f'SW_BRAIN_MAX_BED must be an integer 1..{CONTRACT_MAX_BED}, got {raw!r}')
    return int(raw)


# Mutated in place by set_max_bed so modules that imported these sets see the change.
BEDS: set = set()
DEVICES: set = set()


def set_max_bed(max_bed):
    """Accept beds B01..B<max_bed> and their monitors MON-01..MON-<max_bed>."""
    if type(max_bed) is not int or not 1 <= max_bed <= CONTRACT_MAX_BED:
        raise ValueError(f'max bed must be an integer 1..{CONTRACT_MAX_BED}')
    beds = {f'B{i:02d}' for i in range(1, max_bed + 1)}
    BEDS.clear(); BEDS.update(beds)
    DEVICES.clear(); DEVICES.update(sw_common.device_for_bed(bed) for bed in beds)
    return max_bed


set_max_bed(max_bed_from_env())
MODELS = set(sw_common.MODEL_IDS)
ALARMS = set(sw_common.ALARM_CODES)
PRIORITIES = sw_common.VERDICT_PRIORITY
log = logging.getLogger(__name__)
MAX_PAYLOAD_BYTES = 262144


@dataclass(frozen=True)
class Receipt:
    topic: str
    data: dict
    received_ms: int
    payload_bytes: int
    sender_id: str | None = None  # Only broker-authenticated metadata, never payload identity.
    received_mono_ms: int | None = None


class Bus(Protocol):
    def subscribe(self, topic: str, callback, qos: int = 1): ...
    def publish(self, topic: str, data: dict, qos: int = 1, retain: bool = False): ...


def validate(topic, data):
    """Use the shared schema, then apply existing service input constraints."""
    try:
        errors = sw_common.validate(data)
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise sw_common.MessageError([f'Invalid message: {exc}']) from exc
    if errors:
        raise sw_common.MessageError(errors)
    # Existing detectors convert JSON numbers to native floating point. Python
    # integers can exceed that range even though the shared JSON schema accepts them.
    _check_numeric_range(data)
    if topic != topic_for(data):
        raise sw_common.MessageError(['Topic/payload mismatch'])
    kind = data['type']
    if kind in {'vitals', 'score', 'verdict', 'bedside_check'} and data['bed_id'] not in BEDS:
        raise ValueError('Expected ward bed')
    if kind == 'vitals':
        if data['ts'] % 1000:
            raise ValueError('Expected second-aligned chunk')
    elif kind == 'score' and data['window_s'] != 10:
        raise ValueError('Expected 10-second scores')
    elif kind == 'net_features':
        if data['device_id'] not in DEVICES or data['window_s'] != 5:
            raise ValueError('Expected ward device and 5-second network window')
        for key in ('msgs_per_s', 'bytes_per_s', 'iat_mean_ms', 'iat_std_ms',
                    'payload_mean', 'payload_std', 'senders', 'connects_per_s',
                    'malformed', 'seq_gaps', 'seq_repeats', 'stale_ms'):
            if data[key] is not None and data[key] < 0:
                raise ValueError('Number below minimum')
    elif kind == 'demo_control':
        if re.fullmatch(r'[A-Za-z0-9_-]{1,80}', data['run_id']) is None:
            raise ValueError('Invalid control run ID')
        if data['start_at_s'] > 1200:
            raise ValueError('Seek beyond script')
    return data


def _check_numeric_range(value):
    if isinstance(value, dict):
        for item in value.values(): _check_numeric_range(item)
    elif isinstance(value, (list, tuple)):
        for item in value: _check_numeric_range(item)
    elif type(value) is int:
        try: math.isfinite(value)
        except OverflowError as exc:
            raise ValueError('Number exceeds native detector range') from exc


def decode(topic, payload, received_ms=None, sender_id=None, received_mono_ms=None):
    raw = payload.encode() if isinstance(payload, str) else payload
    if not isinstance(raw, bytes) or len(raw) > MAX_PAYLOAD_BYTES:
        raise ValueError('Invalid payload size')
    data, errors = sw_common.decode(raw)
    if errors:
        raise sw_common.MessageError(errors)
    validate(topic, data)
    return Receipt(topic, data, int(time.time()*1000) if received_ms is None else received_ms,
                   len(raw), sender_id, received_mono_ms)


def encode(topic, data):
    # validate BEFORE encode: the shared encoder sanitizes NaN/inf to null.
    validate(topic, data)
    return sw_common.encode(data)


def publish_checked(bus, topic, data, qos=1, retain=False):
    """Reject before calling even an injected transport; callers count failures."""
    encode(topic, data)
    return bus.publish(topic, data, qos=qos, retain=retain)


class MemoryBus:
    def __init__(self):
        self.published = []; self.subscriptions = []; self.invalid_outgoing = 0; self.cleared = []
    def subscribe(self, topic, callback, qos=1):
        self.subscriptions.append((topic, callback, qos))
    def clear_retained(self, topic):
        self.cleared.append(topic)
        return True
    def publish(self, topic, data, qos=1, retain=False):
        try:
            encode(topic, data)
        except ValueError as exc:
            self.invalid_outgoing += 1
            log.warning('Rejected outgoing message on %s: %s', topic, exc)
            raise
        self.published.append((topic, data, qos, retain))
        return True


class _ReceiptBus(sw_common.Bus):
    """Keep raw size and receipt clocks while shared Bus validates and dispatches.

    The shared callback exposes only (message, topic). Its paho callback hook is
    used here to retain wire bytes and arrival time for existing network checks.
    """
    def __init__(self, *args, owner, system_tls=False, **kwargs):
        self.owner = owner
        self.receipt = None
        super().__init__(*args, **kwargs)
        if system_tls:
            # Bus's CA-file option does not expose TLS with system trust roots.
            self._client.tls_set()

    def _on_message(self, client, userdata, message):
        if len(message.payload) > MAX_PAYLOAD_BYTES:
            self.owner.dropped += 1
            self.owner.invalid_incoming += 1
            log.warning('Rejected incoming message on %s: payload too large', message.topic)
            return
        self.receipt = (message.topic, bytes(message.payload), int(time.time()*1000),
                        int(time.monotonic()*1000))
        try:
            super()._on_message(client, userdata, message)
        finally:
            self.receipt = None


class MQTTBus:
    """Shared MQTT Bus plus bounded main-thread inference and safety overflow."""
    def __init__(self, client_id='sw-brain', max_queue=4096):
        self.callbacks = []; self.queue = queue.Queue(maxsize=max_queue); self.dropped = 0
        self.invalid_incoming = 0; self.invalid_outgoing = 0
        self.safety_pending = {}; self.safety_lock = threading.Lock()
        tls = os.environ.get('SW_MQTT_TLS') == '1'
        ca = os.environ.get('SW_MQTT_CA') if tls else None
        self.bus = _ReceiptBus(
            os.environ.get('SW_MQTT_HOST', 'localhost'),
            int(os.environ.get('SW_MQTT_PORT', '1883')), client_id,
            username=os.environ.get('SW_MQTT_USERNAME') or None,
            password=os.environ.get('SW_MQTT_PASSWORD') or None,
            tls_ca_file=ca, keepalive=60, owner=self, system_tls=tls and not ca)
        self.patterns = set()

    def _on_valid_message(self, data, topic):
        try:
            validate(topic, data)
        except ValueError as exc:
            self.invalid_incoming += 1
            log.warning('Rejected incoming message on %s: %s', topic, exc)
            return
        item = self.bus.receipt
        try:
            self.queue.put_nowait(item)
        except queue.Full:
            self.dropped += 1
            if data['type'] in {'bedside_check', 'demo_control'} or data.get('monitor_alarm'):
                with self.safety_lock:
                    old = self.safety_pending.get(topic)
                    old_data = sw_common.decode(old[1])[0] if old else None
                    if old_data is None or data['ts'] >= old_data['ts']:
                        self.safety_pending[topic] = item

    def subscribe(self, topic, callback, qos=1):
        self.callbacks.append((topic, callback, qos))
        if topic not in self.patterns:
            self.bus.subscribe(topic, self._on_valid_message)
            self.patterns.add(topic)

    def connect(self):
        return self.bus.connect()

    def drain(self, limit=4096):
        with self.safety_lock:
            pending = list(self.safety_pending.values()); self.safety_pending.clear()
        for topic, payload, received, mono in pending:
            self._dispatch(topic, payload, received, mono)
        for _ in range(limit):
            try:
                item = self.queue.get_nowait()
            except queue.Empty:
                break
            self._dispatch(*item)

    def _dispatch(self, topic, payload, received, mono):
        for pattern, callback, qos in self.callbacks:
            if topic_matches(pattern, topic):
                callback(topic, payload, received_ms=received, received_mono_ms=mono)

    def publish(self, topic, data, qos=1, retain=False):
        try:
            encode(topic, data)
        except ValueError as exc:
            self.invalid_outgoing += 1
            log.warning('Rejected outgoing message on %s: %s', topic, exc)
            raise
        if not self.bus.publish(data):
            raise RuntimeError('MQTT publish dropped')
        return True

    def clear_retained(self, topic):
        # Zero-length retained payload = MQTT's clear signal; shared Bus.publish only sends messages.
        return self.bus._client.publish(topic, b'', qos=1, retain=True).rc == 0

    def close(self):
        self.bus.close()
