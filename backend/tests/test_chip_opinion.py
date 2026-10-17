"""Chip messages are displayed, expire, and never participate in clinical decisions."""
import asyncio
import copy
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sw_common import make_alert, make_verdict, topic_for

from sw_api.app import create_app
from sw_api import presenters


def opinion(clock, **fields):
    return {"v": 1, "bed_id": "B03", "ts": clock.ms(), "alarm_code": "VTACH",
            "p_real": 0.87, "label": "real", "threshold": 0.5,
            "model": "M2-cnn-nnpa-2026-10-17", "device": "nnpa:0", "latency_ms": 1.3,
            "heldout_challenge_cinc": 0.623, "heldout_challenge_vtac": 0.665, **fields}


def test_valid_latest_opinion_is_copied_and_exposed_on_http(bus, clock):
    app = create_app(bus=bus, clock=clock)
    with TestClient(app) as client:
        assert client.post('/api/session', json={'role': 'nurse'}).status_code == 200
        assert client.get('/api/beds/B03').json()['chip_opinion'] is None
        msg = opinion(clock)
        assert app.state.runtime.ingest.process(msg, 'ward/chip/B03')
        msg['p_real'] = 0
        assert client.get('/api/beds/B03').json()['chip_opinion'] == opinion(clock)
        beds = client.get('/api/ward').json()['beds']
        assert next(b for b in beds if b['bed_id'] == 'B03')['chip_opinion'] == opinion(clock)
        assert next(b for b in beds if b['bed_id'] == 'B02')['chip_opinion'] is None
        clock.advance(1)
        newer = opinion(clock, p_real=0.2, label='false')
        assert app.state.runtime.ingest.process(newer, 'ward/chip/B03')
        assert app.state.runtime.ingest.process(opinion(clock, ts=clock.ms()-1000), 'ward/chip/B03')
        assert client.get('/api/beds/B03').json()['chip_opinion'] == newer


@pytest.mark.parametrize('bad', [None, [], 'bad', {}, {'v': True}, {'v': 2}, {'ts': 1.1}, {'ts': True},
    {'ts': -1}, {'bed_id': 'B13'}, {'bed_id': []}, {'p_real': '0.87'}, {'p_real': True},
    {'p_real': -0.01}, {'p_real': 1.01}, {'p_real': float('nan')}, {'threshold': float('inf')},
    {'threshold': 2}, {'label': 'maybe'}, {'label': []}, {'alarm_code': 'UNKNOWN'},
    {'model': ''}, {'device': None}, {'latency_ms': -1}, {'latency_ms': float('inf')},
    {'heldout_challenge_cinc': -1}, {'heldout_challenge_vtac': 2}, {'unknown': 1}])
def test_invalid_opinion_is_counted_without_replacing_valid_one(bus, clock, bad):
    runtime = create_app(bus=bus, clock=clock).state.runtime
    good = opinion(clock)
    assert runtime.ingest.process(good, 'ward/chip/B03')
    payload = {**good, **bad} if isinstance(bad, dict) and bad else bad
    assert not runtime.ingest.process(payload, 'ward/chip/B03')
    assert runtime.health()['invalid_messages'] == 1
    assert presenters.bed_detail(runtime.state, 'B03')['chip_opinion'] == good


@pytest.mark.parametrize('field', list(opinion(SimpleNamespace(ms=lambda: 1))))
def test_every_chip_field_is_required(bus, clock, field):
    runtime = create_app(bus=bus, clock=clock).state.runtime
    msg = opinion(clock)
    del msg[field]
    assert not runtime.ingest.process(msg, 'ward/chip/B03')
    assert runtime.ingest.invalid == 1


@pytest.mark.parametrize('topic', ['ward/chip/B04', 'ward/chip/B13', 'ward/chip/B03/extra', 'ward/bed/B03/vitals'])
def test_wrong_topic_is_rejected(bus, clock, topic):
    runtime = create_app(bus=bus, clock=clock).state.runtime
    assert not runtime.ingest.process(opinion(clock), topic)
    assert runtime.ingest.invalid == 1


def test_expiry_clears_http_and_pushes_null_without_vitals(bus, clock):
    runtime = create_app(bus=bus, clock=clock).state.runtime
    async def run():
        client = runtime.hub.subscribe([])
        assert runtime.ingest.process(opinion(clock), 'ward/chip/B03')
        assert (await client.get())['payload']['chip_opinion']['p_real'] == 0.87
        clock.advance(119.999)
        assert presenters.bed(runtime.state, 'B03')['chip_opinion'] is not None
        clock.advance(.001)
        assert presenters.bed(runtime.state, 'B03')['chip_opinion'] is None
        await runtime.tick()
        event = await asyncio.wait_for(client.get(), .5)
        assert event['payload']['bed_id'] == 'B03'
        assert event['payload']['chip_opinion'] is None
    asyncio.run(run())


def test_old_source_timestamp_is_already_stale(bus, clock):
    runtime = create_app(bus=bus, clock=clock).state.runtime
    assert runtime.ingest.process(opinion(clock, ts=clock.ms()-120000), 'ward/chip/B03')
    assert presenters.bed(runtime.state, 'B03')['chip_opinion'] is None


@pytest.mark.parametrize('path', ['/api/demo/run', '/api/demo/reset'])
def test_demo_reset_clears_chip_and_rejects_queued_or_old_messages(bus, clock, path):
    app = create_app(bus=bus, clock=clock)
    with TestClient(app) as client:
        client.post('/api/session', json={'role': 'operator'})
        runtime = app.state.runtime
        msg = opinion(clock)
        assert runtime.ingest.process(msg, 'ward/chip/B03')
        generation = runtime.ingest.generation
        assert client.post(path, json={}).status_code == 202
        assert client.get('/api/beds/B03').json()['chip_opinion'] is None
        assert not runtime.ingest.process(msg, 'ward/chip/B03', generation)
        assert not runtime.ingest.process(msg, 'ward/chip/B03')
        clock.advance(1)
        assert runtime.ingest.process(opinion(clock), 'ward/chip/B03')


def test_disagreeing_chip_does_not_change_verdict_alert_action_trust_or_ladder(bus, clock):
    runtime = create_app(bus=bus, clock=clock).state.runtime
    for msg in [make_verdict(bed_id='B03', window_start=clock.ms()//5000*5000, ts=clock.ms(),
                            verdict='EMERGENCY', trust=.9, confidence=.9, scores={}),
                make_alert(alert_id='a', bed_id='B03', verdict='EMERGENCY', text='Go now', to=['A1'], ts=clock.ms())]:
        assert runtime.ingest.process(msg, topic_for(msg))
    before = copy.deepcopy(presenters.bed_detail(runtime.state, 'B03'))
    alerts, actions, scores = copy.deepcopy((runtime.state.alerts, runtime.state.actions, runtime.store.scores))
    assert runtime.ingest.process(opinion(clock, p_real=.1, label='false'), 'ward/chip/B03')
    after = presenters.bed_detail(runtime.state, 'B03')
    after['chip_opinion'] = None
    assert after == before
    assert (runtime.state.alerts, runtime.state.actions, runtime.store.scores) == (alerts, actions, scores)
    assert bus.sent == []


def test_real_bus_routes_chip_json_and_keeps_existing_validation(bus, clock):
    from sw_api.chip import ChipBus
    from paho.mqtt.client import Client, CallbackAPIVersion
    # Real paho client, no network: exercise the production decode boundary.
    mqtt = ChipBus('localhost', 1883, 'chip-test', client_factory=lambda _: Client(CallbackAPIVersion.VERSION2))
    runtime = create_app(bus=mqtt, clock=clock).state.runtime
    async def run():
        runtime.ingest.bind(asyncio.get_running_loop())
        mqtt.subscribe('ward/chip/+', runtime.ingest.callback)
        payloads = [(json.dumps(opinion(clock)).encode(), False), (b'{bad', False),
                    (b'[]', False), (b'\xff', False), (b'', False),
                    (json.dumps(opinion(clock)).encode(), True),
                    (b'[' * 600 + b'0' + b']' * 600, False),
                    (b'{"nested":' * 600 + b'0' + b'}' * 600, False)]
        for payload, retain in payloads:
            mqtt._client.on_message(mqtt._client, None, SimpleNamespace(topic='ward/chip/B03', payload=payload, retain=retain))
        await asyncio.sleep(0)
        assert presenters.bed(runtime.state, 'B03')['chip_opinion'] == opinion(clock)
        assert runtime.health()['invalid_messages'] == 7
        assert mqtt.stats()['handler_errors'] == 0
        mqtt._client.on_message(mqtt._client, None, SimpleNamespace(topic='ward/bed/B03/vitals', payload=b'{}'))
        assert runtime.health()['invalid_messages'] == 8
        mqtt.close()
    asyncio.run(run())
