import pytest

from sw_brain.decision import decide
from sw_brain.detectors import DetectorSuite, result
from sw_brain.extended import PressureDrift
from sw_brain.service import BedState


@pytest.mark.parametrize('model', ['M1', 'M2', 'M3', 'M4', 'M5', 'M6'])
@pytest.mark.parametrize('eligible', [False, True])
def test_null_score_is_unknown_even_if_marked_eligible(model, eligible):
    scores = {f'M{i}': {'score': 0., 'reason': 'Observed clear', 'extra': {'eligible': True}}
              for i in range(1, 7)}
    scores[model] = {'score': None, 'reason': 'Unavailable', 'extra': {'eligible': eligible}}
    verdict = decide('B01', 0, 10000, scores)
    assert verdict['verdict'] == 'UNSURE'
    assert verdict['scores'][model] is None
    assert decide('B01', 0, 10000, scores, alarm=True)['verdict'] == 'EMERGENCY'


def test_trust_ignores_null_integrity_scores_and_preserves_real_zero():
    scores = {f'M{i}': {'score': 0., 'reason': 'Observed clear', 'extra': {'eligible': True}}
              for i in range(1, 7)}
    assert decide('B01', 0, 10000, scores)['verdict'] == 'NORMAL'
    scores['M3']['score'] = None
    scores['M4']['score'] = .3
    verdict = decide('B01', 0, 10000, scores)
    assert verdict['trust'] == pytest.approx(.7)
    assert verdict['verdict'] == 'UNSURE'
    scores['M4']['score'] = scores['M5']['score'] = None
    verdict = decide('B01', 0, 10000, scores)
    assert verdict['trust'] == 1.
    assert verdict['verdict'] == 'UNSURE'


@pytest.mark.parametrize('score', [0., .9, None])
def test_ineligible_result_never_keeps_a_numeric_score(score):
    observation = result(score, 'Baseline warming', eligible=False)
    assert observation['score'] is None
    assert observation['extra']['eligible'] is False
    assert observation['extra']['unavailable_reason']


def test_no_observations_produce_six_null_scores():
    scores = DetectorSuite().evaluate(None, BedState('B01'), 10000)
    for observation in scores.values():
        assert observation['score'] is None
        assert observation['extra']['eligible'] is False
        assert observation['extra']['unavailable_reason']


@pytest.mark.parametrize('model', ['M1', 'M2', 'M3', 'M4', 'M5', 'M6'])
def test_detector_failure_is_null_and_does_not_break_other_checks(model, frame, monkeypatch):
    suite = DetectorSuite()
    state = BedState('B01')
    message = frame(9)
    state.last_message = message
    state.messages.append({'message': message, 'received_ms': 9000,
                           'payload_bytes': 100, 'sender_id': None})
    window = {'bed_id': 'B01', 'window_start': 0,
              'ecg': message['ecg'] * 10, 'ppg': message['ppg'] * 10}

    def fail(*args):
        raise RuntimeError('Unavailable test detector')

    monkeypatch.setattr(suite.detectors[model], 'evaluate', fail)
    scores = suite.evaluate(window, state, 10000)
    assert len(scores) == 6
    assert scores[model]['score'] is None
    assert scores[model]['extra']['eligible'] is False
    assert 'RuntimeError' in scores[model]['extra']['unavailable_reason']
    assert decide('B01', 0, 10000, scores)['verdict'] == 'UNSURE'


def test_pressure_missing_cuff_warmup_and_expired_comparison_are_null():
    detector = PressureDrift()
    state = BedState('B08')
    for ts in (10000, 20000, 30000, 400001):
        message = {'ts': ts, 'abp': [100.] * 125,
                   'nibp': {'map': 80, 'ts': ts} if ts in (20000, 30000) else None}
        state.messages.clear()
        state.messages.append({'message': message, 'received_ms': ts})
        observation = detector({'bed_id': 'B08'}, state, ts)
        assert observation['score'] is None
        assert observation['extra']['eligible'] is False
        assert observation['extra']['unavailable_reason']


def test_unsure_reason_names_the_blocking_checks_inconclusive_first():
    scores = {f'M{i}': {'score': 0., 'reason': 'Observed clear', 'extra': {'eligible': True}}
              for i in range(1, 7)}
    scores['M2'] = {'score': None, 'reason': 'Waiting for 10 seconds of ECG', 'extra': {'eligible': False}}
    scores['M3'] = {'score': .74, 'reason': 'ECG rate 109 bpm differs from pulse rate 135 bpm', 'extra': {'eligible': True}}
    verdict = decide('B04', 0, 10000, scores)
    assert verdict['verdict'] == 'UNSURE'
    assert verdict['reasons'] == ['Body-match check: ECG rate 109 bpm differs from pulse rate 135 bpm',
                                  'Emergency check: Waiting for 10 seconds of ECG']
