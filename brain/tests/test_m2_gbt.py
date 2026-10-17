import json

import numpy as np
import pytest

from sw_brain.detectors import EmergencyDetector
from sw_brain.io import MemoryBus
from sw_brain.m2gbt import ARTIFACT, MODEL_VERSION, SHA256, GbtM2
from sw_brain.service import BedState, BrainService

TYPES = {'ASYSTOLE', 'BRADY', 'TACHY', 'VTACH', 'VFIB'}


def run_alarm(frame, code, suite_m2=None, abp=None, alarm_at=10):
    service = BrainService(MemoryBus())
    if suite_m2 is not None:
        service.suite.detectors['M2'] = suite_m2
    for i in range(alarm_at + 5):          # alarm frame plus 4 s, so a live window also exists
        alarm = {'code': code, 'priority': 'high'} if i == alarm_at else None
        service.receive('ward/bed/B01/vitals', json.dumps(frame(i, monitor_alarm=alarm, abp=abp)), received_ms=i * 1000)
    verdict = service.tick((alarm_at + 5) * 1000)[0]
    m2 = [d for t, d, *_ in service.bus.published if t.endswith('/score/M2')][-1]
    return service, verdict, m2


def test_pinned_artifact_loads_and_covers_every_alarm_type():
    model = GbtM2()._load()
    assert model.spec['model_version'] == MODEL_VERSION
    assert set(model.spec['thresholds']) == TYPES
    assert model.spec['trained_on']['machine'] == 's390x'
    assert len(SHA256) == 64


def test_feature_code_matches_model_feature_names():
    from m2gbt.features import window_features
    model = GbtM2()._load()
    t = np.arange(1250) / 125
    feats = window_features(np.sin(2 * np.pi * t).tolist(), None, None, 'VTACH')
    assert set(model.names) <= set(feats)


@pytest.mark.parametrize('code', sorted(TYPES))
def test_prealarm_window_uses_trees_and_alarm_stays_emergency(frame, code):
    _, verdict, m2 = run_alarm(frame, code)
    assert m2['model_version'] == 'M2-gbt-2026-10-17'
    assert m2['extra']['path'] == 'gbt_prealarm'
    assert 0 <= m2['score'] <= 1
    assert m2['extra']['alarm_code'] == code
    # Safety: the monitor alarm is never suppressed by a low M2 score.
    assert verdict['verdict'] in {'EMERGENCY', 'BOTH'} and verdict['priority'] == 'high'


def test_low_probability_cannot_suppress_or_downgrade_alarm(frame):
    class Zero:
        names = []; spec = {'thresholds': {c: .5 for c in TYPES}}
        def predict_proba(self, x): return 0.0
    _, verdict, m2 = run_alarm(frame, 'VTACH', EmergencyDetector(gbt=GbtM2(model=Zero())))
    assert m2['score'] == 0.0 and m2['extra']['positive'] is False
    assert verdict['verdict'] == 'EMERGENCY' and verdict['priority'] == 'high'


def test_tampered_artifact_falls_back_to_live_rule(frame, tmp_path):
    bad = tmp_path / 'm2.json'
    bad.write_bytes(ARTIFACT.read_bytes() + b' ')
    _, verdict, m2 = run_alarm(frame, 'BRADY', EmergencyDetector(gbt=GbtM2(path=bad)))
    assert m2['model_version'] == 'M2-live-2026-10-17'
    assert m2['extra']['path'] == 'live_ecg_rule'
    assert 'SHA-256' in m2['extra']['gbt']['extra']['unavailable_reason']
    assert verdict['verdict'] == 'EMERGENCY'


def test_without_full_prealarm_window_live_rule_is_used(frame):
    state = BedState('B01', last_alarm_code='BRADY', alarm_until_ms=20000)
    window = {'window_start': 0, 'ecg': frame()['ecg'] * 10, 'monitor_alarms': []}
    result = EmergencyDetector().evaluate(window, state, 10000)
    assert result['extra']['path'] == 'live_ecg_rule'
    assert result['extra']['gbt']['extra']['unavailable_reason'] == 'no_full_prealarm_window'


def test_prealarm_window_carries_arterial_line_when_present(frame):
    service, _, m2 = run_alarm(frame, 'ASYSTOLE', abp=[80.0 + (i % 125 < 40) * 30 for i in range(125)])
    window = service.beds['B01'].prealarm_window
    assert window['abp'] is not None and len(window['abp']) == 1250
    assert m2['extra']['features']['abp_mean_mmhg'] is not None
    service, _, _ = run_alarm(frame, 'ASYSTOLE')
    assert service.beds['B01'].prealarm_window['abp'] is None


def test_result_is_cached_per_bed_and_window():
    calls = []
    class Counting:
        names = []; spec = {'thresholds': {c: .5 for c in TYPES}}
        def predict_proba(self, x): calls.append(1); return .7
    gbt = GbtM2(model=Counting())
    w = {'bed_id': 'B01', 'window_start': 0, 'ecg': [0.1] * 1250, 'ppg': None}
    assert gbt.evaluate(w, 'VTACH')['score'] == .7
    gbt.evaluate(w, 'VTACH')
    gbt.evaluate({**w, 'bed_id': 'B02'}, 'VTACH')
    assert len(calls) == 2
