"""M2 model-security tests: a damaged or swapped artifact, or hostile inputs, must never stop
the brain or weaken an alarm.

What "logged" means here: GbtM2 records the failure (``GbtM2.failure``) and the brain publishes
it on ``ward/bed/<bed>/score/M2`` as ``extra.gbt.extra.unavailable_reason`` (the backend stores
every score message). The live ECG rule then explains the alarm; the alarm itself stays
EMERGENCY because M2 never suppresses, delays or downgrades it.
"""
import hashlib
import json
import math

import numpy as np
import pytest

from sw_brain.detectors import EmergencyDetector
from sw_brain.io import MemoryBus
from sw_brain.m2gbt import ARTIFACT, ARTIFACT_2, SHA256, SHA256_2, GbtM2
from sw_brain.service import BedState, BrainService

TYPES = ('ASYSTOLE', 'BRADY', 'TACHY', 'VFIB', 'VTACH')
LIVE_RULE = 'M2-live-2026-10-17'


def run_alarm(frame, code, gbt, alarm_at=10):
    service = BrainService(MemoryBus())
    service.suite.detectors['M2'] = EmergencyDetector(gbt=gbt)
    for i in range(alarm_at + 5):
        alarm = {'code': code, 'priority': 'high'} if i == alarm_at else None
        service.receive('ward/bed/B01/vitals', json.dumps(frame(i, monitor_alarm=alarm)), received_ms=i * 1000)
    verdict = service.tick((alarm_at + 5) * 1000)[0]
    m2 = [d for t, d, *_ in service.bus.published if t.endswith('/score/M2')][-1]
    return verdict, m2


def assert_fell_back_to_rule(verdict, m2, gbt, reason_part):
    assert m2['model_version'] == LIVE_RULE and m2['extra']['path'] == 'live_ecg_rule'
    reason = m2['extra']['gbt']['extra']['unavailable_reason']
    assert reason_part in reason
    assert gbt.failure is not None and reason_part in gbt.failure      # recorded on the adapter too
    assert verdict['verdict'] in {'EMERGENCY', 'BOTH'} and verdict['priority'] == 'high'


def write(tmp_path, name, data):
    p = tmp_path / name
    p.write_bytes(data)
    return p, hashlib.sha256(data).hexdigest()


def both_paths(path, sha):
    """GbtM2 whose 1-lead model is (path, sha) and with no 2-lead artifact configured."""
    return GbtM2(path=path, sha256=sha, path2=None)


# ---- tampered artifact bytes -> SHA-256 mismatch -> not loaded

@pytest.mark.parametrize('mutate', [
    lambda b: b[:-1] + bytes([b[-1] ^ 1]),                        # one bit flipped
    lambda b: b.replace(b'"threshold":', b'"threshold" :', 1),      # whitespace only, same model
    lambda b: b.replace(b'"value":[', b'"value":[9.0,', 1),         # a leaf value poisoned
], ids=['bit_flip', 'whitespace', 'poisoned_leaf'])
def test_tampered_1lead_artifact_is_refused_and_rule_explains(frame, tmp_path, mutate):
    raw = ARTIFACT.read_bytes()
    bad = mutate(raw)
    assert bad != raw
    path, _ = write(tmp_path, 'm2.json', bad)
    gbt = GbtM2(path=path, path2=None)                               # pinned SHA256 kept
    verdict, m2 = run_alarm(frame, 'VTACH', gbt)
    assert_fell_back_to_rule(verdict, m2, gbt, 'SHA-256 mismatch')


def test_swapped_artifacts_are_refused(frame, tmp_path):
    # The 2-lead file placed where the 1-lead file belongs (valid model, wrong pin).
    path, _ = write(tmp_path, 'm2.json', ARTIFACT_2.read_bytes())
    gbt = GbtM2(path=path, path2=None)
    verdict, m2 = run_alarm(frame, 'BRADY', gbt)
    assert_fell_back_to_rule(verdict, m2, gbt, 'SHA-256 mismatch')


def test_missing_artifact_file_falls_back(frame, tmp_path):
    gbt = GbtM2(path=tmp_path / 'absent.json', path2=None)
    verdict, m2 = run_alarm(frame, 'TACHY', gbt)
    assert_fell_back_to_rule(verdict, m2, gbt, 'FileNotFoundError')


def test_pinned_digests_match_the_shipped_files():
    assert hashlib.sha256(ARTIFACT.read_bytes()).hexdigest() == SHA256
    assert hashlib.sha256(ARTIFACT_2.read_bytes()).hexdigest() == SHA256_2


# ---- hash matches but the content is broken (defence in depth behind the pin)

@pytest.mark.parametrize('data,reason', [
    (lambda raw: raw[: len(raw) // 2], 'JSONDecodeError'),          # truncated JSON
    (lambda raw: b'\x00\xffnot json at all' * 50, 'JSONDecodeError'),
    (lambda raw: b'', 'JSONDecodeError'),
    (lambda raw: json.dumps({'format': 'pickle'}).encode(), 'unknown model format'),
    (lambda raw: json.dumps([1, 2, 3]).encode(), 'AttributeError'),
], ids=['truncated', 'garbage', 'empty', 'wrong_format', 'not_an_object'])
def test_broken_artifact_with_matching_hash_falls_back(frame, tmp_path, data, reason):
    path, sha = write(tmp_path, 'm2.json', data(ARTIFACT.read_bytes()))
    gbt = both_paths(path, sha)
    verdict, m2 = run_alarm(frame, 'ASYSTOLE', gbt)
    assert_fell_back_to_rule(verdict, m2, gbt, reason)


def _spec():
    return json.loads(ARTIFACT.read_bytes())


def test_wrong_feature_count_in_trees_falls_back(frame, tmp_path):
    # Trees that index a feature the input vector does not have (artifact for another feature set).
    spec = _spec()
    spec['trees'][0]['feature'] = [len(spec['feature_names']) + 5] * len(spec['trees'][0]['feature'])
    path, sha = write(tmp_path, 'm2.json', json.dumps(spec).encode())
    gbt = both_paths(path, sha)
    verdict, m2 = run_alarm(frame, 'VTACH', gbt)
    assert_fell_back_to_rule(verdict, m2, gbt, 'IndexError')


def test_unknown_feature_names_cannot_crash_and_alarm_stands(frame, tmp_path):
    # Fewer / renamed features: unknown names become NaN (the trees' missing-value branch).
    spec = _spec()
    spec['feature_names'] = [f'not_a_feature_{i}' for i in range(len(spec['feature_names']))]
    path, sha = write(tmp_path, 'm2.json', json.dumps(spec).encode())
    verdict, m2 = run_alarm(frame, 'VTACH', both_paths(path, sha))
    assert m2['extra']['path'] == 'gbt_prealarm' and 0 <= m2['score'] <= 1
    assert verdict['verdict'] == 'EMERGENCY' and verdict['priority'] == 'high'


def test_missing_threshold_for_alarm_type_falls_back(frame, tmp_path):
    spec = _spec()
    del spec['thresholds']['VFIB']
    path, sha = write(tmp_path, 'm2.json', json.dumps(spec).encode())
    gbt = both_paths(path, sha)
    verdict, m2 = run_alarm(frame, 'VFIB', gbt)
    assert_fell_back_to_rule(verdict, m2, gbt, 'no threshold for alarm VFIB')


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf'), 1e308])
def test_poisoned_leaf_values_never_return_invalid_probability(frame, value):
    class Poisoned:
        names = []; spec = {'thresholds': {c: .5 for c in TYPES}}
        def predict_proba(self, x):
            return float('nan') if value != value else (1.0 / (1.0 + math.exp(-value)) if value > -700 else 0.0)
    gbt = GbtM2(model=Poisoned(), path2=None)
    verdict, m2 = run_alarm(frame, 'BRADY', gbt)
    if value != value:
        assert_fell_back_to_rule(verdict, m2, gbt, 'invalid probability')
    else:
        assert 0 <= m2['score'] <= 1
    assert verdict['verdict'] == 'EMERGENCY' and verdict['priority'] == 'high'


# ---- NaN / inf / extreme inputs: no crash, alarm never suppressed

def _window(ecg, ecg2=None, ppg=None, abp=None):
    return {'bed_id': 'B01', 'window_start': 0, 'monitor_alarms': [], 'ecg': ecg, 'ecg2': ecg2,
            'ppg': ppg, 'abp': abp}


def _sig():
    t = np.arange(1250) / 125
    return (0.8 * np.exp(-((t * 125 % 125 - 20) / 3) ** 2)).tolist()


HOSTILE = {
    'nan_everywhere': lambda: [float('nan')] * 1250,
    'inf_spikes': lambda: [float('inf') if i % 50 == 0 else v for i, v in enumerate(_sig())],
    'neg_inf': lambda: [-float('inf')] * 1250,
    'huge': lambda: [1e300 * (-1) ** i for i in range(1250)],
    'all_none': lambda: [None] * 1250,
    'constant': lambda: [0.0] * 1250,
    'wrong_length': lambda: _sig()[:1000] + [None] * 250,
}


@pytest.mark.parametrize('name', sorted(HOSTILE))
@pytest.mark.parametrize('code', TYPES)
def test_hostile_prealarm_inputs_never_crash_or_suppress(name, code):
    x = HOSTILE[name]()
    for window in (_window(x), _window(_sig(), ecg2=x), _window(_sig(), ppg=x, abp=x), _window(x, x, x, x)):
        gbt = GbtM2()
        out = gbt.evaluate(window, code)
        assert out['status'] in {'active', 'unavailable'}
        if out['status'] == 'active':
            assert 0 <= out['score'] <= 1 and math.isfinite(out['score'])
        # Through the detector, with the alarm held: still a score result, never a crash.
        state = BedState('B01', last_alarm_code=code, alarm_until_ms=10 ** 12, prealarm_window=window)
        r = EmergencyDetector(gbt=gbt).evaluate(window, state, 1)
        assert r['score'] is None or 0 <= r['score'] <= 1


def test_nan_inf_vitals_messages_are_rejected_and_alarm_stays_emergency(frame):
    service = BrainService(MemoryBus())
    for i in range(15):
        alarm = {'code': 'VTACH', 'priority': 'high'} if i == 10 else None
        msg = frame(i, monitor_alarm=alarm)
        if i in (3, 7):
            msg['ecg'] = [float('nan')] * 125
        if i == 5:
            msg['ppg'] = [float('inf')] * 125
        service.receive('ward/bed/B01/vitals', json.dumps(msg), received_ms=i * 1000)
    verdict = service.tick(15000)[0]
    assert verdict['verdict'] in {'EMERGENCY', 'BOTH'} and verdict['priority'] == 'high'
    assert service.invalid_incoming >= 1      # non-finite samples are refused at the input contract


def test_m2_crash_inside_detector_cannot_stop_the_tick(frame):
    class Exploding:
        def reset(self): pass
        def evaluate(self, window, code): raise RuntimeError('boom')
    service = BrainService(MemoryBus())
    service.suite.detectors['M2'] = EmergencyDetector(gbt=Exploding())
    for i in range(15):
        alarm = {'code': 'VFIB', 'priority': 'high'} if i == 10 else None
        service.receive('ward/bed/B01/vitals', json.dumps(frame(i, monitor_alarm=alarm)), received_ms=i * 1000)
    verdict = service.tick(15000)[0]
    assert verdict['verdict'] in {'EMERGENCY', 'BOTH'} and verdict['priority'] == 'high'
