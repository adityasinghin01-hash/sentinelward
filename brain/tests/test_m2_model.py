import hashlib
import json
import pickle
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from sw_brain.m2_model import M2Model
from sw_brain.io import MemoryBus
from sw_brain.service import BrainService


ENTERED = threading.Event()
RELEASE = threading.Event()


class ProbabilityModel:
    classes_ = np.array([0, 1])

    def predict_proba(self, values):
        return np.array([[1 - row[0], row[0]] for row in values])


class SlowModel(ProbabilityModel):
    def predict_proba(self, values):
        ENTERED.set()
        RELEASE.wait(5)
        return super().predict_proba(values)


@pytest.fixture
def bundle(tmp_path):
    package = tmp_path / 'ml_v2' / 'm2gbt'
    package.mkdir(parents=True)
    (package / '__init__.py').write_text("MODEL_VERSION = 'M2-gbt-2026-10-17'\n")
    (package / 'features.py').write_text(
        'from . import MODEL_VERSION\n'
        'def window_features(ecg, ppg=None, abp=None, alarm_code=None):\n'
        '    return {"value": ecg[0], "pressure": abp[0] if abp else float("nan"),\n'
        '            "vt": float(alarm_code == "VTACH")}\n')
    def write(model=None, **updates):
        data = dict(model_version='M2-gbt-2026-10-17', model=model or ProbabilityModel(),
                    feature_names=['value', 'vt', 'pressure'],
                    thresholds={code: .61 for code in ('VTACH', 'VFIB', 'BRADY', 'TACHY', 'ASYSTOLE')})
        data.update(updates)
        path = tmp_path / 'model.pkl'
        path.write_bytes(pickle.dumps(data))
        path.with_suffix('.pkl.sha256').write_text(hashlib.sha256(path.read_bytes()).hexdigest() + '  model.pkl\n')
        return path
    return write


def window(value=.62, bed='B01', start=0):
    return dict(bed_id=bed, device_id='MON-' + bed[1:], window_start=start,
                ecg=[value] * 1250, ppg=[None] * 1250, abp=[80.] * 1250)


def await_score(hook, source, code='VTACH'):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        output = hook.score(source, code)
        if output is not None:
            return output
        if hook.unavailable_reason not in {'model_pending', 'model_busy'}:
            return None
        time.sleep(.005)
    pytest.fail('Model worker did not finish')


@pytest.mark.parametrize('code', ['VTACH', 'VFIB', 'BRADY', 'TACHY', 'ASYSTOLE'])
def test_verified_pickle_uses_named_features_and_per_alarm_threshold(bundle, code):
    hook = M2Model(bundle())
    output = await_score(hook, window(), code)
    assert output['score'] == .62
    assert output['threshold'] == .61 and output['positive'] is True
    assert output['model_version'] == 'M2-gbt-2026-10-17'
    assert await_score(hook, window(.02, 'B02'), code)['positive'] is False


def test_hash_mismatch_prevents_deserialization_and_feature_execution(bundle):
    path = bundle()
    marker = path.parent / 'executed'
    class Payload:
        def __reduce__(self):
            return Path.touch, (marker,)
    path.write_bytes(pickle.dumps(Payload()))
    features = path.parent / 'ml_v2' / 'm2gbt' / 'features.py'
    features.write_text(f'from pathlib import Path\nPath({str(marker)!r}).touch()\n')
    hook = M2Model(path)
    assert await_score(hook, window()) is None
    assert 'SHA-256' in hook.unavailable_reason
    assert not marker.exists()


@pytest.mark.parametrize('updates', [
    {'model_version': 'old'}, {'thresholds': {'VTACH': float('nan')}},
    {'thresholds': {'VTACH': 1.1}}, {'feature_names': ['missing']},
])
def test_invalid_bundle_falls_back(bundle, updates):
    hook = M2Model(bundle(**updates))
    assert await_score(hook, window()) is None
    assert hook.unavailable_reason not in {'model_pending', 'model_busy', ''}


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -.1, 1.1])
def test_invalid_probability_falls_back(bundle, value):
    hook = M2Model(bundle())
    assert await_score(hook, window(value)) is None


def test_missing_bundle_or_hash_falls_back(bundle, monkeypatch):
    monkeypatch.delenv('SW_M2_MODEL', raising=False)
    hook = M2Model()
    assert hook.score(window(), 'VTACH') is None
    assert hook.unavailable_reason == 'model_not_configured'
    path = bundle()
    path.with_suffix('.pkl.sha256').unlink()
    hook = M2Model(path)
    assert await_score(hook, window()) is None
    assert 'FileNotFoundError' in hook.unavailable_reason


def test_portable_json_matches_current_export_schema(bundle):
    path = bundle().with_suffix('.json')
    tree = dict(feature=[0, 0, 0], threshold=[.5, 0, 0], missing_left=[1, 0, 0],
                left=[1, 0, 0], right=[2, 0, 0], leaf=[0, 1, 1], value=[0, -2, 2])
    path.write_text(json.dumps(dict(format='sentinelward-gbt-json-1',
                                   model_version='M2-gbt-2026-10-17', feature_names=['value'],
                                   thresholds={'VTACH': .7}, baseline=0, trees=[tree])))
    path.with_suffix('.json.sha256').write_text(hashlib.sha256(path.read_bytes()).hexdigest())
    hook = M2Model(path)
    assert await_score(hook, window())['score'] == pytest.approx(.8807970779778823)
    assert await_score(hook, window(.1, 'B02'))['positive'] is False


def test_slow_model_never_blocks_alarm_and_reset_discards_old_result(bundle, frame, monkeypatch):
    ENTERED.clear()
    RELEASE.clear()
    monkeypatch.setenv('SW_M2_MODEL', str(bundle(SlowModel())))
    bus = MemoryBus()
    service = BrainService(bus)
    for second in range(11):
        service.receive('ward/bed/B01/vitals', json.dumps(frame(second,
                        monitor_alarm={'code': 'BRADY', 'priority': 'high'} if second == 10 else None)),
                        received_ms=second * 1000)
    started = time.monotonic()
    try:
        verdict = service.tick(10000)[0]
        assert time.monotonic() - started < .2
        assert verdict['verdict'] in {'EMERGENCY', 'BOTH'}
        assert ENTERED.wait(2)
        hook = service.suite.detectors['M2'].model
        hook.reset()
    finally:
        RELEASE.set()
    # Same key after a reset must use this run's samples, not the old future.
    output = await_score(hook, window(.02), 'BRADY')
    assert output['score'] == .02


def test_configured_model_scores_prealarm_and_preserves_emergency(bundle, frame, monkeypatch):
    monkeypatch.setenv('SW_M2_MODEL', str(bundle()))
    bus = MemoryBus()
    service = BrainService(bus)
    for second in range(11):
        message = frame(second, ecg=[.02] * 125,
                        monitor_alarm={'code': 'VTACH', 'priority': 'high'} if second == 10 else None)
        service.receive('ward/bed/B01/vitals', json.dumps(message), received_ms=second * 1000)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        verdict = service.tick(10000)[0]
        assert verdict['verdict'] in {'EMERGENCY', 'BOTH'}
        model_scores = [m for _, m, _, _ in bus.published if m.get('model') == 'M2']
        if model_scores[-1]['extra']['path'] == 'configured_model':
            break
        time.sleep(.005)
    else:
        pytest.fail('Configured M2 was never published')
    assert model_scores[-1]['score'] == .02
    assert model_scores[-1]['model_version'] == 'M2-gbt-2026-10-17'
    assert 'research' not in model_scores[-1]['extra']
