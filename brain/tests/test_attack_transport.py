"""Duplicate network abuse must not masquerade as changed patient data."""
from copy import deepcopy
import json

import pytest

from sw_brain.decision import decide
from sw_brain.detectors import ReplayDetector
from sw_brain.io import MemoryBus
from sw_brain.service import BrainService


def send(service, message, at, sender):
    return service.receive(f"ward/bed/{message['bed_id']}/vitals", json.dumps(message),
                           received_ms=at, received_mono_ms=at, sender_id=sender)


def traffic(frame, *, kind, first=False):
    service = BrainService(MemoryBus())
    for sec in range(40):
        original = frame(sec)
        copy = deepcopy(original)
        active = 20 <= sec < (28 if kind == 'flood' else 40)
        flood = active and (kind == 'flood' or (kind == 'mixed' and sec < 28))
        if first and active:
            send(service, copy, sec*1000, 'attacker')
        send(service, original, sec*1000+10, 'monitor')
        if active:
            if not first:
                send(service, copy, sec*1000+20, 'attacker')
            for i in range(1, 50 if flood else 1):
                send(service, copy, sec*1000+20*i, 'attacker')
    return service


@pytest.mark.parametrize('first', [False, True])
def test_b11_duplicate_flood_is_device_attack(frame, first):
    service = traffic(frame, kind='flood', first=first)
    # Score while the flood is still in the 10 second receipt window.
    verdict = service.tick(35000)[0]
    assert verdict['scores']['M4'] < .8
    assert verdict['verdict'] == 'DEVICE_ATTACK'
    assert service.display_snapshot('B01') is not None


@pytest.mark.parametrize('first', [False, True])
def test_b12_paced_copies_are_unsure_then_clear(frame, first):
    service = traffic(frame, kind='paced', first=first)
    verdict = service.tick(40000)[0]
    assert .5 <= verdict['scores']['M4'] < .8
    assert .5 <= verdict['scores']['M5'] < .8
    assert verdict['verdict'] == 'UNSURE'
    for sec in range(40, 61):
        send(service, frame(sec), sec*1000, 'monitor')
    assert service.tick(60000)[0]['verdict'] == 'UNSURE'
    service.receive('ward/bed/B01/bedside', json.dumps(dict(v=1, type='bedside_check',
                    bed_id='B01', ts=60000, result='patient_ok', by='staff:nurse')), received_ms=60000)
    assert service.tick(60000)[0]['verdict'] == 'NORMAL'


@pytest.mark.parametrize('first', [False, True])
def test_b07_flood_then_paced_sender_is_tampering_and_alarm_is_both(frame, first):
    service = traffic(frame, kind='mixed', first=first)
    assert service.tick(40000)[0]['verdict'] == 'TAMPERING'
    send(service, frame(40, monitor_alarm={'code':'VFIB', 'priority':'high'}), 40000, 'monitor')
    assert service.tick(40000)[0]['verdict'] == 'BOTH'
    assert service.display_snapshot('B01') is not None


@pytest.mark.parametrize('kind', ['flatline', 'drift', 'numeric', 'alarm', 'seq_only'])
@pytest.mark.parametrize('first', [False, True])
def test_content_conflicts_preserve_b06_b10_and_other_tampering(frame, kind, first):
    service = BrainService(MemoryBus())
    for sec in range(10):
        send(service, frame(sec, abp=[90.]*125), sec*1000, 'monitor')
    real = frame(10, abp=[90.]*125)
    altered = deepcopy(real)
    if kind == 'flatline':
        altered.update(ecg=[0.]*125, monitor_alarm={'code':'ASYSTOLE','priority':'high'})
    elif kind == 'drift': altered['abp'] = [105.]*125
    elif kind == 'numeric': altered['hr'] = 20
    elif kind == 'alarm': altered['monitor_alarm'] = {'code':'VTACH','priority':'high'}
    else: altered['seq'] += 1
    for sender, msg in ([('attacker', altered), ('monitor', real)] if first else
                        [('monitor', real), ('attacker', altered)]):
        send(service, msg, 10000, sender)
    observation = service.suite.detectors['M4'].evaluate(None, service.beds['B01'], 10000)
    assert observation['score'] >= .8
    assert observation['extra']['independent_evidence']
    assert service.tick(10000)[0]['verdict'] == ('BOTH' if kind in ('flatline','alarm') else 'TAMPERING')


def test_b05_old_replay_stays_strong_even_without_reference(frame):
    service = BrainService(MemoryBus())
    send(service, frame(600), 600000, 'monitor')
    send(service, frame(360), 601000, 'attacker')
    verdict = service.tick(605000)[0]
    assert verdict['scores']['M4'] >= .8
    assert verdict['verdict'] == 'TAMPERING'


def test_waveform_replay_remains_independent_evidence(frame):
    service = BrainService(MemoryBus())
    for sec in range(20):
        send(service, frame(sec), sec*1000, 'monitor')
        if sec == 9: service.tick(10000)
    assert service.tick(20000)[0]['verdict'] == 'TAMPERING'


def test_paced_tail_from_other_sender_cannot_combine_with_flood(frame):
    service = traffic(frame, kind='flood')
    for sec in range(28, 40):
        send(service, frame(sec), sec*1000+50, 'unrelated')
    observation = service.suite.detectors['M4'].evaluate(None, service.beds['B01'], 40000)
    assert observation['score'] < .8


def test_duplicate_flood_cannot_combine_with_unrelated_m3_mismatch(frame):
    service = traffic(frame, kind='flood')
    state = service.beds['B01']
    scores = {f'M{i}':dict(score=.05, reason='clear', extra={'eligible':True}) for i in range(1,7)}
    scores['M3']['score'] = .99
    scores['M4'] = service.suite.detectors['M4'].evaluate(None, state, 35000)
    scores['M5'] = service.suite.detectors['M5'].evaluate(None, state, 35000)
    assert decide('B01', 25000, 35000, scores)['verdict'] == 'DEVICE_ATTACK'
    # Emergency always wins, including a patient-not-OK report and the pressure safety flag.
    for flag in ('alarm', 'patient_not_ok', 'confirmed_low_pressure'):
        assert decide('B01', 25000, 35000, scores, **{flag:True})['verdict'] == 'EMERGENCY'


def test_clean_copy_exception_does_not_hide_changed_accepted_frame(frame):
    service = BrainService(MemoryBus())
    for sec in range(10): send(service, frame(sec), sec*1000, 'monitor')
    changed = frame(10, hr=10)
    send(service, changed, 10000, 'attacker')
    send(service, frame(10), 10010, 'monitor')
    verdict = service.tick(15000)[0]
    assert verdict['verdict'] == 'TAMPERING'


def test_topic7_repeats_of_verified_paced_copies_stay_weak(frame):
    from sw_common import make_net_features
    service = traffic(frame, kind='paced')
    network = make_net_features(device_id='MON-01', window_start=35000, window_s=5,
                                msgs_per_s=2, seq_repeats=5, senders=2, bytes_per_s=None,
                                iat_mean_ms=None, iat_std_ms=None, payload_mean=None,
                                payload_std=None, connects_per_s=None, malformed=None,
                                seq_gaps=None, stale_ms=None)
    service.receive('net/device/MON-01/features', json.dumps(network), received_ms=40000)
    verdict = service.tick(40000)[0]
    assert verdict['verdict'] == 'UNSURE'
    assert verdict['scores']['M5'] == .6


def test_unpaired_accepted_frame_does_not_get_clean_copy_exception(frame):
    service = traffic(frame, kind='paced')
    # A fresh forged frame has no corresponding monitor frame to verify it.
    send(service, frame(40, hr=10), 40000, 'attacker')
    observation = service.suite.detectors['M4'].evaluate(None, service.beds['B01'], 40000)
    assert not observation['extra']['duplicate_only']
