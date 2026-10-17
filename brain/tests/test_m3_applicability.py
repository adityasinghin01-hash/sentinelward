"""ECG-grounded applicability must not be controlled by a substituted pulse."""
from types import SimpleNamespace

import numpy as np
import pytest

from sw_brain.decision import decide
from sw_brain.detectors import QualityDetector, result
from sw_brain.extended import BodyMismatch


def window(irregular_ecg=True, irregular_ppg=True, start=0):
    t = np.arange(1250) / 125
    irregular = [.3, .7, 1.8, 2.3, 3.6, 4., 5.1, 5.6, 6.9, 7.3, 8.4, 8.9]
    regular = np.arange(.3, 10, .8)
    ecg = sum(np.exp(-((t-s)/.018)**2) for s in (irregular if irregular_ecg else regular))
    ppg = sum(np.exp(-((t-s-.2)/.045)**2) for s in (irregular if irregular_ppg else regular))
    return dict(bed_id='B01', window_start=start,
                ecg=(ecg+.002*np.sin(2*np.pi*3*t)).tolist(),
                ppg=(ppg+.002*np.sin(2*np.pi*2*t)).tolist())


def test_irregular_ecg_pauses_comparison_without_claiming_a_body_match():
    w = window()
    assert QualityDetector().evaluate(w, None, 10000)['score'] < .5
    observation = BodyMismatch()(w, SimpleNamespace(), 10000)
    assert observation['score'] is None
    assert observation['extra']['not_applicable'] is True
    assert observation['extra']['eligible'] is False
    checks = {f'M{i}': result(0., 'Observed clear') for i in range(1, 7)}
    checks['M3'] = observation
    assert decide('B01', 0, 10000, checks)['verdict'] == 'NORMAL'
    assert decide('B01', 0, 10000, checks, alarm=True)['verdict'] == 'EMERGENCY'
    assert decide('B01', 0, 10000, checks, offline=True)['verdict'] == 'UNSURE'


def test_irregular_forged_ppg_cannot_pause_a_regular_ecg():
    model = BodyMismatch()
    for start in range(0, 40000, 10000):
        model(window(False, False, start), SimpleNamespace(), start+10000)
    observations = [model(window(False, True, start), SimpleNamespace(), start+10000)
                    for start in (40000, 45000, 50000)]
    assert all(not r['extra'].get('not_applicable', False) for r in observations)
    assert all(r['score'] is not None for r in observations)
    assert observations[-1]['score'] >= .8


@pytest.mark.parametrize('channel,kind', [('ecg', 'missing'), ('ppg', 'missing'),
                                         ('ecg', 'flat'), ('ecg', 'noise')])
def test_missing_or_m1_unusable_signal_is_never_exempt(channel, kind):
    w = window()
    if kind == 'missing':
        w[channel] = [None]*1250
    elif kind == 'flat':
        w[channel] = [0.]*1250
    else:
        w[channel] = np.sin(2*np.pi*50*np.arange(1250)/125).tolist()
    assert QualityDetector().evaluate(w, None, 10000)['score'] >= .5
    observation = BodyMismatch()(w, SimpleNamespace(), 10000)
    assert observation['score'] is None
    assert not observation['extra'].get('not_applicable', False)


def test_paused_windows_cannot_teach_a_pulse_timing_baseline():
    model = BodyMismatch()
    for start in range(0, 60000, 10000):
        observation = model(window(start=start), SimpleNamespace(), start+10000)
        assert observation['extra']['not_applicable'] is True
    regular = model(window(False, False, 60000), SimpleNamespace(), 70000)
    assert regular['score'] < .5
    assert regular['extra']['baseline_samples'] == 0


def test_flat_pulse_cannot_turn_sparse_ecg_into_measured_disagreement():
    w = window(False, False)
    t = np.arange(1250)/125
    w['ecg'] = (sum(np.exp(-((t-s)/.018)**2) for s in (.3, 1.1, 1.9))
                + .002*np.sin(2*np.pi*3*t)).tolist()
    w['ppg'] = [0.]*1250
    observation = BodyMismatch()(w, SimpleNamespace(), 10000)
    assert observation['score'] is None  # sparse ECG and M1-unusable pulse
    assert not observation['extra'].get('not_applicable', False)


def test_recovery_reason_explains_persisting_disagreement():
    from test_live_extended import waves
    model = BodyMismatch()
    for start in (0, 5000, 10000):
        model(waves(ppg_rate=110, start=start), SimpleNamespace(), start+10000)
    recovery = model(waves(start=15000), SimpleNamespace(), 25000)
    assert recovery['score'] >= .8
    assert 'recent' in recovery['reason'].lower()
