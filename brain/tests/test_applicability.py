import json
import math

import pytest

from sw_brain.decision import decide
from sw_brain.detectors import EmergencyDetector, result
from sw_brain.extended import PressureDrift
from sw_brain.io import MemoryBus
from sw_brain.service import BedState, BrainService


@pytest.mark.parametrize('m3_score,expected', [(0., 'NORMAL'), (None, 'UNSURE')])
def test_normal_requires_all_applicable_checks_but_not_m2_or_m6(m3_score, expected):
    scores = {f'M{i}': result(0., 'Observed clear') for i in range(1, 7)}
    scores['M2'] = result(None, 'No monitor alarm', not_applicable=True)
    scores['M6'] = result(None, 'No arterial line', not_applicable=True)
    scores['M3'] = result(m3_score, 'Pulse timing check')
    verdict = decide('B01', 0, 10000, scores)
    assert verdict['verdict'] == expected
    assert verdict['scores']['M2'] is verdict['scores']['M6'] is None
    assert decide('B01', 0, 10000, scores, offline=True)['verdict'] == 'UNSURE'
    assert decide('B01', 0, 10000, scores, alarm=True)['verdict'] == 'EMERGENCY'


@pytest.mark.parametrize('seconds,expected', [(10, 'NORMAL'), (40, 'NORMAL')])  # rate agreement is checked from the first window
def test_no_line_no_alarm_bed_publishes_applicability_and_can_become_normal(frame, seconds, expected):
    bus = MemoryBus()
    service = BrainService(bus)
    for sec in range(seconds):
        # Small shape changes avoid replay while preserving pulse timing.
        width = 3 + 1.5 * (sec // 10)
        ecg = [.8 * math.exp(-((i - 20) / width) ** 2) + .02 * math.sin(i)
               for i in range(125)]
        service.receive('ward/bed/B01/vitals', json.dumps(frame(sec, ecg=ecg)), received_ms=sec * 1000)
        if sec % 10 == 9:
            verdict = service.tick((sec + 1) * 1000)[0]
    assert verdict['verdict'] == expected
    for model in ('M2', 'M6'):
        published = [m for t, m, _, _ in bus.published if t.endswith('/score/' + model)][-1]
        wire = [m for t, m, _, _ in bus.published if t.endswith('/verdict')][-1]
        assert published['score'] is None
        assert published['extra']['not_applicable'] is True
        assert published['reason']
        assert published['extra']['unavailable_reason']
        assert wire['scores'][model] is None
    assert verdict['scores']['M3'] < .5  # checked from the first window (rates agree)
    if seconds == 40:
        assert service.beds['B01'].last_trusted_ts == 40000


@pytest.mark.parametrize('window', [None, {'ecg': [None] * 1250, 'monitor_alarms': []}])
def test_m2_without_alarm_is_not_applicable_even_when_ecg_unknown(window):
    observation = EmergencyDetector().evaluate(window, BedState('B01'), 10000)
    assert observation['score'] is None
    assert observation['extra']['not_applicable'] is True
    assert observation['reason']


@pytest.mark.parametrize('source', ['window', 'held', 'hold_boundary'])
def test_m2_alarm_is_applicable_and_missing_ecg_stays_unknown(source):
    state = BedState('B01')
    window = {'window_start': 0, 'ecg': [None] * 1250, 'monitor_alarms': []}
    if source == 'window':
        window['monitor_alarms'] = [{'code': 'VTACH', 'priority': 'high'}]
    else:
        state.last_alarm_code = 'VTACH'
        state.alarm_until_ms = 10000 if source == 'hold_boundary' else 20000
    observation = EmergencyDetector().evaluate(window, state, 10000)
    assert observation['score'] is None
    assert not observation['extra'].get('not_applicable', False)


@pytest.mark.parametrize('source', ['window', 'held', 'hold_boundary'])
def test_m2_evaluates_the_alarm_with_observed_ecg(frame, source):
    state = BedState('B01')
    window = {'window_start': 0, 'ecg': frame()['ecg'] * 10, 'monitor_alarms': []}
    if source == 'window':
        window['monitor_alarms'] = [{'code': 'BRADY', 'priority': 'high'}]
    else:
        state.last_alarm_code = 'BRADY'
        state.alarm_until_ms = 10000 if source == 'hold_boundary' else 20000
    observation = EmergencyDetector().evaluate(window, state, 10000)
    assert observation['score'] == .05
    assert observation['extra']['alarm_code'] == 'BRADY'
    assert observation['extra']['eligible'] is True
    assert not observation['extra'].get('not_applicable', False)


def test_expired_alarm_without_window_alarm_makes_m2_not_applicable():
    state = BedState('B01', last_alarm_code='VTACH', alarm_until_ms=9999)
    observation = EmergencyDetector().evaluate(None, state, 10000)
    assert observation['score'] is None
    assert observation['extra']['not_applicable'] is True


def test_active_alarm_without_window_is_unknown():
    state = BedState('B01', last_alarm_code='VTACH', alarm_until_ms=20000)
    observation = EmergencyDetector().evaluate(None, state, 10000)
    assert observation['score'] is None
    assert not observation['extra'].get('not_applicable', False)


@pytest.mark.parametrize('next_window_abp', [False, True])
def test_m6_only_line_samples_in_current_window_make_it_applicable(next_window_abp):
    detector = PressureDrift()
    state = BedState('B01')
    state.messages.append({'message': {'ts': 0, 'abp': [100.] * 125, 'nibp': None}, 'received_ms': 0})
    first = detector({'bed_id': 'B01', 'window_start': 0}, state, 10000)
    # Line present but no paired cuff yet: no drift evidence either way, so it must not block NORMAL.
    assert first['extra']['not_applicable'] is True
    assert 'cuff' in first['reason']
    state.messages.append({'message': {'ts': 19000, 'abp': None, 'nibp': None}, 'received_ms': 19000})
    if next_window_abp:
        state.messages.append({'message': {'ts': 20000, 'abp': [100.] * 125, 'nibp': None}, 'received_ms': 20000})
    observation = detector({'bed_id': 'B01', 'window_start': 10000}, state, 20000)
    assert observation['score'] is None
    assert observation['extra']['not_applicable'] is True


def test_not_applicable_m2_still_allows_device_attack():
    scores = {f'M{i}': result(0., 'Observed clear') for i in range(1, 7)}
    scores['M2'] = result(None, 'No monitor alarm', not_applicable=True)
    scores['M6'] = result(None, 'No arterial line', not_applicable=True)
    scores['M5'] = result(.95, 'Network attack')
    assert decide('B01', 0, 10000, scores)['verdict'] == 'DEVICE_ATTACK'
