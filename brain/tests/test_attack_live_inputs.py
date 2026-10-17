"""Exercise anonymous MQTT receipts with real, delayed extractor aggregation."""
from copy import deepcopy
import json

import pytest

from sw_brain.decision import decide
from sw_brain.detectors import ReplayDetector
from sw_brain.io import MemoryBus, encode
from sw_brain.service import BrainService
from tests_system.attack_replay_eval import LiveInputs


def live_traffic(frame, kind, first=False, logs=True):
    service = BrainService(MemoryBus())
    live = LiveInputs(service, origin=0, beds=('B01',))
    live.extractor.logs_available = logs
    for sec in range(40):
        message = frame(sec)
        topic = 'ward/bed/B01/vitals'
        payload = encode(topic, message)
        active = 20 <= sec < (28 if kind == 'flood' else 40)
        flood = active and (kind == 'flood' or (kind == 'mixed' and sec < 28))
        # Extractor sees the source first even if brain's monitor receipt lags.
        live.observe(topic, payload, sec*1000, 'MON-01')
        if first and active:
            live.receive(topic, payload, sec*1000, 'attacks')
        service.receive(topic, payload, received_ms=sec*1000+10,
                        received_mono_ms=sec*1000+10, sender_id=None)
        if active and not first:
            live.receive(topic, payload, sec*1000+20, 'attacks')
        for ms in range(20, 1000, 20):
            if flood and ms > 20:
                live.receive(topic, payload, sec*1000+ms, 'attacks')
            live.publish_due(sec*1000+ms)
    return service, live


def test_replay_input_uses_real_counts_and_delayed_feature_delivery(frame):
    service = BrainService(MemoryBus())
    live = LiveInputs(service, origin=0, beds=('B01',))
    topic = 'ward/bed/B01/vitals'
    for sec in range(10):
        payload = encode(topic, frame(sec))
        live.receive(topic, payload, sec*1000, 'MON-01')
        if sec >= 5:
            live.receive(topic, payload, sec*1000+20, 'attacks')
        live.publish_due(sec*1000+200)
    state = service.beds['B01']
    assert all(r['sender_id'] is None for r in state.messages)
    assert state.network['msgs_per_s'] is None  # initial partial coverage
    live.publish_due(10000)
    assert state.network['window_start'] == 0  # not delivered at the scoring boundary
    live.publish_due(10200)
    assert state.network['window_start'] == 5000
    assert state.network['received_ms'] == 10200
    assert state.network['msgs_per_s'] == 2
    assert state.network['senders'] == 2
    assert state.network['seq_repeats'] == 5
    assert state.network['seq_gaps'] == 0
    assert state.network['malformed'] == 0
    assert state.network['stale_ms'] == 1000


@pytest.mark.parametrize('first', [False, True])
def test_anonymous_duplicate_flood_does_not_turn_body_mismatch_into_tampering(frame, first):
    service, _ = live_traffic(frame, 'flood', first)
    state = service.beds['B01']
    scores = {f'M{i}':dict(score=.05, reason='clear', extra={'eligible':True}) for i in range(1,7)}
    scores['M3']['score'] = .99
    scores['M4'] = service.suite.detectors['M4'].evaluate(None, state, 35000)
    scores['M5'] = service.suite.detectors['M5'].evaluate(None, state, 35000)
    assert scores['M4']['extra']['duplicate_only']
    assert scores['M5']['score'] >= .8
    assert decide('B01', 25000, 35000, scores)['verdict'] == 'DEVICE_ATTACK'
    for flag in ('alarm', 'patient_not_ok', 'confirmed_low_pressure'):
        assert decide('B01', 25000, 35000, scores, **{flag:True})['verdict'] == 'EMERGENCY'


@pytest.mark.parametrize('first', [False, True])
def test_anonymous_paced_copies_request_check_until_patient_ok(frame, first):
    service, live = live_traffic(frame, 'paced', first)
    verdict = service.tick(40000)[0]
    assert verdict['verdict'] == 'UNSURE'
    assert .5 <= verdict['scores']['M4'] < .8
    assert .5 <= verdict['scores']['M5'] < .8
    for sec in range(40, 61):
        live.receive('ward/bed/B01/vitals', encode('ward/bed/B01/vitals', frame(sec)), sec*1000, 'MON-01')
        live.publish_due(sec*1000+200)
    assert service.tick(60000)[0]['verdict'] == 'UNSURE'
    service.receive('ward/bed/B01/bedside', json.dumps(dict(v=1, type='bedside_check',
                    bed_id='B01', ts=60000, result='patient_ok', by='staff:nurse')), received_ms=60000)
    assert service.tick(60000)[0]['verdict'] == 'NORMAL'


@pytest.mark.parametrize('first', [False, True])
def test_anonymous_changed_content_keeps_independent_tampering_evidence(frame, first):
    service, live = live_traffic(frame, 'paced', first)
    topic = 'ward/bed/B01/vitals'
    real = frame(40)
    changed = deepcopy(real)
    changed['hr'] = 10
    for i, message in enumerate((changed, real) if first else (real, changed)):
        live.receive(topic, encode(topic, message), 40000+i*10, 'MON-01' if message is real else 'attacks')
    assert service.tick(45000)[0]['verdict'] == 'TAMPERING'


def test_sender_count_cannot_establish_same_publisher_across_flood_and_paced_tail(frame):
    service, _ = live_traffic(frame, 'mixed')
    value = service.suite.detectors['M4'].evaluate(None, service.beds['B01'], 40000)
    # The broker count cannot distinguish continuing attacks from an unrelated
    # publisher that started after the flooding publisher disconnected.
    assert not value['extra']['independent_evidence']
    assert value['score'] == .6


def test_missing_broker_logs_do_not_invent_publisher_identity(frame):
    service, _ = live_traffic(frame, 'paced', logs=False)
    state = service.beds['B01']
    assert state.network['senders'] is None
    value = service.suite.detectors['M4'].evaluate(None, state, 40000)
    assert not value['extra']['sender_identity_available']
    assert not value['extra']['independent_evidence']


@pytest.mark.parametrize('problem', ['wrong_device', 'future', 'stale', 'not_received'])
def test_sender_count_is_used_only_for_a_recent_completed_matching_window(frame, problem):
    service, _ = live_traffic(frame, 'paced')
    state = service.beds['B01']
    if problem == 'wrong_device': state.network['device_id'] = 'MON-02'
    elif problem == 'future': state.network['window_start'] = 40000
    elif problem == 'stale': state.network['window_start'] = 20000
    else: state.network['received_ms'] = 40001
    value = ReplayDetector().evaluate(None, state, 40000)
    assert value['score'] < .5
