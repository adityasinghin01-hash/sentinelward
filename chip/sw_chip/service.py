"""Live AI-chip second opinion: ward/bed/+/vitals in, ward/chip/<bed_id> out.

For every bed alarm the brain scores with M2 (new alarm episode with a full 10 s pre-alarm
window), runs the CNN on the z17 NNPA and publishes one QoS 1, non-retained message. It
only listens to vitals and only publishes on ward/chip/+: it cannot change any verdict,
alert or action.

Environment:
  SW_CHIP_HOST (localhost) SW_CHIP_PORT (1883) SW_CHIP_USER / SW_CHIP_PASSWORD (or
  SW_CHIP_PASSWORD_FILE) SW_CHIP_CA (CA file -> TLS) SW_CHIP_CLIENT_ID (sw-chip)
  SW_CHIP_DEVICE (nnpa|cpu, default: nnpa if available)
"""
from __future__ import annotations

import json
import logging
import os
import queue
import signal
import threading
import time

from .tracker import AlarmTracker, check_vitals

log = logging.getLogger('sw_chip')
VITALS_SUB = 'ward/bed/+/vitals'


def chip_topic(bed_id):
    return f'ward/chip/{bed_id}'


class ChipService:
    """Transport-free core: on_vitals() queues new alarm windows; a worker scores and publishes."""

    def __init__(self, model, publish, clock_ms=lambda: int(time.time() * 1000)):
        self.model, self.publish, self.clock_ms = model, publish, clock_ms
        self.tracker = AlarmTracker()
        self.jobs = queue.Queue(maxsize=256)
        self.stats = {'vitals': 0, 'invalid': 0, 'alarms': 0, 'published': 0, 'errors': 0, 'dropped': 0}
        self._stop = threading.Event()
        self._worker = None

    def on_vitals(self, topic, payload, now_ms=None):
        self.stats['vitals'] += 1
        try:
            message = json.loads(payload)
        except (ValueError, UnicodeDecodeError):
            self.stats['invalid'] += 1
            return None
        reason = check_vitals(topic, message)
        if reason:
            self.stats['invalid'] += 1
            return None
        job = self.tracker.ingest(message, self.clock_ms() if now_ms is None else now_ms)
        if job is not None:
            self.stats['alarms'] += 1
            try:
                self.jobs.put_nowait((message['bed_id'],) + job)
            except queue.Full:
                self.stats['dropped'] += 1
        return job

    def score(self, bed_id, code, ts, window):
        try:
            msg = self.model.message(bed_id, ts, code, window)
        except Exception as exc:
            self.stats['errors'] += 1
            log.warning('chip score failed for %s %s: %s', bed_id, code, exc)
            return None
        if self.publish(chip_topic(bed_id), json.dumps(msg, separators=(',', ':'))):
            self.stats['published'] += 1
        log.info('chip %s %s p_real=%.3f %s %s %.2f ms', bed_id, code, msg['p_real'], msg['label'],
                 msg['device'], msg['latency_ms'])
        return msg

    def drain(self):
        """Score every queued job now (tests)."""
        out = []
        while True:
            try:
                bed_id, code, ts, window = self.jobs.get_nowait()
            except queue.Empty:
                return out
            out.append(self.score(bed_id, code, ts, window))

    def start(self):
        def run():
            while not self._stop.is_set():
                try:
                    bed_id, code, ts, window = self.jobs.get(timeout=0.5)
                except queue.Empty:
                    continue
                self.score(bed_id, code, ts, window)
        self._worker = threading.Thread(target=run, name='sw-chip-worker', daemon=True)
        self._worker.start()

    def stop(self):
        self._stop.set()
        if self._worker:
            self._worker.join(timeout=5)


def _password():
    path = os.environ.get('SW_CHIP_PASSWORD_FILE')
    if path:
        return open(path).read().strip()
    return os.environ.get('SW_CHIP_PASSWORD')


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
    from paho.mqtt import client as mqtt
    from .model import ChipModel
    model = ChipModel()
    # Warm-up so the first live alarm does not pay the device's first-call cost.
    warm = {'ecg': [0.0] * 1250, 'ppg': [0.0] * 1250, 'abp': None}
    for _ in range(3):
        model.predict(warm, 'VTACH')
    log.info('model %s sha256 %s on %s', model.meta['model'], model.sha256[:12], model.device)
    host = os.environ.get('SW_CHIP_HOST', 'localhost')
    port = int(os.environ.get('SW_CHIP_PORT', '1883'))
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                         client_id=os.environ.get('SW_CHIP_CLIENT_ID', 'sw-chip'))
    user = os.environ.get('SW_CHIP_USER')
    if user:
        client.username_pw_set(user, _password())
    ca = os.environ.get('SW_CHIP_CA')
    if ca:
        client.tls_set(ca_certs=ca)
    client.reconnect_delay_set(1, 30)

    def publish(topic, payload):
        info = client.publish(topic, payload, qos=1, retain=False)
        return info.rc == mqtt.MQTT_ERR_SUCCESS

    svc = ChipService(model, publish)

    def on_connect(c, userdata, flags, rc, props=None):
        log.info('connected to %s:%s rc=%s', host, port, rc)
        if not getattr(rc, 'is_failure', False):
            c.subscribe(VITALS_SUB, qos=0)

    def on_message(c, userdata, msg):
        svc.on_vitals(msg.topic, msg.payload)

    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = lambda c, u, f, rc, p=None: log.warning('disconnected rc=%s', rc)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *a: stop.set())
    signal.signal(signal.SIGINT, lambda *a: stop.set())
    svc.start()
    client.connect_async(host, port, keepalive=30)
    client.loop_start()
    last = time.time()
    while not stop.wait(1):
        if time.time() - last >= 60:
            log.info('stats %s', json.dumps(svc.stats, sort_keys=True))
            last = time.time()
    client.loop_stop()
    client.disconnect()
    svc.stop()
    log.info('stopped; stats %s', json.dumps(svc.stats, sort_keys=True))


if __name__ == '__main__':
    main()
