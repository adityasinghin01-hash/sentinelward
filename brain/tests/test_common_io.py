"""Contract and transport regressions for the shared I/O seam."""
import json
from types import SimpleNamespace

import pytest
import sw_common
from sw_common import make_score, make_verdict
from sw_brain.io import MemoryBus, MQTTBus, decode, encode
from sw_brain.service import BrainService


@pytest.mark.parametrize('change', [
    {'window_start': 123}, {'extra': {'nested': float('nan')}}, {'score': None},
])
def test_outgoing_invalid_scores_never_reach_memory_transport(change, caplog):
    bus = MemoryBus()
    message = make_score(bed_id='B03', model='M3', model_version='test',
                         window_start=5000, score=.4, label='mismatch', reason='Observed')
    message.update(change)
    with pytest.raises(ValueError):
        bus.publish('ward/bed/B03/score/M3', message)
    assert not bus.published
    assert bus.invalid_outgoing == 1
    assert 'Rejected outgoing' in caplog.text


def test_incoming_contract_fields_and_nested_nonfinite_are_checked(frame):
    missing = frame()
    del missing['nibp']
    with pytest.raises(ValueError):
        decode('ward/bed/B01/vitals', json.dumps(missing))
    with pytest.raises(ValueError):
        encode('ward/bed/B01/vitals', frame(extra={'bad': float('inf')}))


def test_unavailable_scores_do_not_hide_emergency_wire_verdict(frame, caplog):
    class Capture:
        def __init__(self): self.published = []
        def subscribe(self, *args, **kwargs): pass
        def publish(self, topic, data, **kwargs): self.published.append((topic, data, kwargs))

    bus = Capture()
    service = BrainService(bus)
    message = frame(9, monitor_alarm={'code': 'VTACH', 'priority': 'high'})
    service.receive('ward/bed/B01/vitals', json.dumps(message), received_ms=9000)
    internal = service.tick(10123)[0]
    assert internal['verdict'] == 'EMERGENCY'
    assert any(value is None for value in internal['scores'].values())
    assert bus.published
    assert all(sw_common.validate(data) == [] for _, data, _ in bus.published)
    wire = next(data for _, data, _ in bus.published if data['type'] == 'verdict')
    assert wire['verdict'] == 'EMERGENCY' and wire['window_start'] == 0
    assert wire['last_trusted_ts'] is None
    assert all(value is not None for value in wire['scores'].values())
    assert wire['unavailable_scores']['M1']['score'] is None
    assert wire['unavailable_scores']['M1']['extra']['unavailable_reason']
    assert service.invalid_outgoing == sum(v is None for v in internal['scores'].values())
    assert 'Rejected outgoing' in caplog.text


def test_rejected_brain_input_is_counted(frame):
    service = BrainService(MemoryBus())
    assert not service.receive('ward/bed/B01/vitals', json.dumps(frame(device_id='MON-03')))
    assert service.invalid_incoming == 1
    assert not service.beds


class FakeClient:
    """Network-only double; the shared Bus remains real."""
    def __init__(self, client_id):
        self.client_id = client_id
        self.sent = []; self.subscriptions = []; self.auth = None; self.tls = None
        self.rc = 0
    def username_pw_set(self, username, password): self.auth = (username, password)
    def tls_set(self, **kwargs): self.tls = kwargs
    def tls_set_context(self, context): self.tls = context
    def reconnect_delay_set(self, **kwargs): pass
    def connect_async(self, host, port, keepalive): self.connection = (host, port, keepalive)
    def loop_start(self): self.on_connect(self, None, {}, 0)
    def loop_stop(self): pass
    def disconnect(self): pass
    def subscribe(self, topic, qos): self.subscriptions.append((topic, qos))
    def publish(self, topic, payload, qos, retain):
        self.sent.append((topic, payload, qos, retain))
        return SimpleNamespace(rc=self.rc)
    def deliver(self, topic, data):
        self.on_message(self, None, SimpleNamespace(topic=topic, payload=json.dumps(data).encode()))


@pytest.fixture
def transport(monkeypatch):
    import sw_common.bus
    clients = []
    def factory(client_id):
        client = FakeClient(client_id); clients.append(client); return client
    monkeypatch.setattr(sw_common.bus, '_paho_client', factory)
    for suffix in ('HOST', 'PORT', 'USERNAME', 'PASSWORD', 'TLS', 'CA'):
        monkeypatch.delenv('SW_MQTT_' + suffix, raising=False)
    return clients


def test_shared_mqtt_bus_keeps_raw_receipts_and_safety_overflow(transport, frame):
    bus = MQTTBus(max_queue=1)
    service = BrainService(bus)
    bus.connect()
    client = transport[0]
    assert client.auth is None and client.tls is None
    original = frame(8)
    client.deliver('ward/bed/B01/vitals', original)
    client.deliver('ward/bed/B01/vitals', frame(9, monitor_alarm={'code': 'VTACH', 'priority': 'high'}))
    # A newer bedside check must win over an older one despite queue pressure.
    check = sw_common.make_bedside_check(bed_id='B01', ts=11000, result='patient_not_ok', by='staff:nurse')
    client.deliver('ward/bed/B01/bedside', check)
    client.deliver('ward/bed/B01/bedside', {**check, 'ts': 10000, 'result': 'patient_ok'})
    client.deliver('ward/bed/B01/vitals', frame(10, device_id='MON-03'))
    bus.drain()
    state = service.beds['B01']
    assert state.patient_not_ok and state.alarm_until_ms > 0
    assert next(r for r in state.messages if r['message']['ts'] == 8000)['payload_bytes'] == len(json.dumps(original).encode())
    assert all(r.get('received_mono_ms') is not None for r in state.messages)
    assert bus.dropped == 3
    assert bus.bus.stats()['invalid'] == 1
    assert isinstance(bus.bus, sw_common.Bus)
    bus.close()


@pytest.mark.parametrize('with_ca', [False, True])
def test_shared_mqtt_credentials_and_opt_in_tls(transport, monkeypatch, tmp_path, with_ca):
    monkeypatch.setenv('SW_MQTT_USERNAME', 'brain')
    monkeypatch.setenv('SW_MQTT_PASSWORD', 'test-password')
    monkeypatch.setenv('SW_MQTT_TLS', '1')
    monkeypatch.setenv('SW_MQTT_PORT', '8883')
    if with_ca:
        ca = tmp_path / 'ca.pem'; ca.write_text('test certificate')
        monkeypatch.setenv('SW_MQTT_CA', str(ca))
    bus = MQTTBus()
    assert transport[0].auth == ('brain', 'test-password')
    assert transport[0].tls is not None
    bus.close()


def test_mqtt_never_sanitizes_invalid_output_into_a_publish(transport, caplog):
    bus = MQTTBus()
    message = make_verdict(bed_id='B03', window_start=5000, verdict='UNSURE',
                           confidence=.5, trust=1., scores={})
    with pytest.raises(ValueError):
        bus.publish('ward/bed/B03/verdict', {**message, 'extra': {'bad': float('nan')}}, retain=True)
    with pytest.raises(ValueError):
        bus.publish('ward/bed/B04/verdict', message, retain=True)
    assert transport[0].sent == []
    assert bus.invalid_outgoing == 2
    assert 'Rejected outgoing' in caplog.text
    assert bus.publish('ward/bed/B03/verdict', message, retain=True)
    assert transport[0].sent[-1][2:] == (1, True)
    bus.close()
