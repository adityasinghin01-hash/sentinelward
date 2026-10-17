"""Optional immutable research adapters. Failures always leave live rules available."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError

import numpy as np
from scipy.ndimage import minimum_filter1d
from scipy.signal import resample_poly

ROOT = Path(__file__).resolve().parents[2]
# Pinned digest from ml/results/M5_EXTERNAL_REVIEW.md; verify before importing loader.
M5_SHA256 = '200d8c8ae43fb11071d53072193c24ce0fe833ea6e943d9a5e5ee872d669e41f'


def upsample(window):
    """125 -> 250 Hz, ECG then PPG; mask full FIR support, including edges."""
    rows = [[np.nan if v is None else v for v in window[ch]] for ch in ('ecg', 'ppg')]
    source = np.asarray(rows, dtype=np.float64)
    if source.shape != (2, 1250):
        raise ValueError('Expected full 10 s ECG and PPG window')
    valid = np.isfinite(source)
    safe = minimum_filter1d(valid.astype(np.uint8), size=23, axis=1,
                            mode='constant', cval=0).astype(bool)
    mask = np.repeat(safe, 2, axis=1)
    signal = resample_poly(np.where(valid, source, 0), 2, 1, axis=1)
    return np.asarray(np.where(mask, signal, 0), dtype=np.float32), mask


class Research:
    def __init__(self, *, models=None, m5_path=None, channel_order_verified=False, timeout_s=.1):
        self.models = models
        self.m5_path = Path(m5_path or ROOT / 'security/m5_network_witness/artifacts/m5_model_baseline.joblib')
        self.channel_order_verified = channel_order_verified
        self._m5 = None
        self.failures = {}
        self.timeout_s = timeout_s
        self._executor = None
        self._pending = {}
        self._active = None

    def reset(self):
        for _, future in self._pending.values():
            future.cancel()
        self._pending.clear()

    def _execute(self, name, key, task):
        """One bounded optional worker in this process, never one environment per model."""
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='sw-artifact')
        previous = self._pending.get(name)
        if previous and previous[0] != key and not previous[1].done():
            return self._failure(name, TimeoutError('Artifact worker busy; live rule used'))
        if previous is None or previous[0] != key:
            if self._active is not None and not self._active.done():
                return self._failure(name, TimeoutError('Artifact worker busy; live rule used'))
            self._pending[name] = (key, self._executor.submit(task))
            self._active = self._pending[name][1]
        try:
            return self._pending[name][1].result(timeout=self.timeout_s)
        except TimeoutError:
            return self._failure(name, TimeoutError('Artifact deadline exceeded; live rule used'))

    def m2(self, window):
        key = (window.get('bed_id'),window.get('window_start', id(window)))
        return self._execute('M2', key, lambda: self._m2(window))

    def m4(self, reference, candidate):
        if not self.channel_order_verified:
            return self._failure('M4', ValueError('Research channel order not verified'))
        key = (candidate.get('bed_id'),reference.get('window_start'), candidate.get('window_start'))
        return self._execute('M4', key, lambda: self._m4(reference, candidate))

    def m5(self, features, device):
        key = (device, tuple(sorted(features.items())))
        return self._execute('M5', key, lambda: self._m5_predict(features, device))

    def _models(self):
        if self.models is None:
            sys.path.insert(0, str(ROOT / 'ml'))
            from sentinelward_ml.inference import SentinelWardModels
            self.models = SentinelWardModels()  # per-model SHA checks before loading
        return self.models

    @staticmethod
    def _result(score, threshold, extra):
        score, threshold = float(score), float(threshold)
        if not all(math.isfinite(v) and 0 <= v <= 1 for v in (score, threshold)):
            raise ValueError('Artifact returned invalid score or threshold')
        return {'status': 'active', 'score': score, 'threshold': threshold,
                'positive': score >= threshold, 'extra': extra}

    def _failure(self, name, exc):
        reason = f'{type(exc).__name__}: {exc}'[:240]
        self.failures[name] = reason
        return {'status': 'unavailable', 'extra': {'unavailable_reason': reason}}

    def _m2(self, window):
        try:
            signal, mask = upsample(window)
            result = self._models().predict_m2(signal, mask)
            primary = result['seeds']['20261015']
            return self._result(primary['probability'], primary['threshold'], {
                **result, 'resampled_from_125hz': True, 'source_hz': 125, 'target_hz': 250,
                'domain_warning': 'Single lead; upsampling does not restore lost bandwidth',
                'valid_fraction': mask.mean(axis=1).tolist(),
                'source_window_start': window.get('window_start')})
        except Exception as exc:
            return self._failure('M2', exc)

    def _m4(self, reference, candidate):
        if not self.channel_order_verified:
            return self._failure('M4', ValueError('Research channel order not verified'))
        try:
            ref, rm = upsample(reference)
            cand, cm = upsample(candidate)
            result = self._models().predict_m4(ref, cand, rm, cm)
            if not result.get('channel_order_verified'):
                raise ValueError('Artifact channel order not verified')
            return self._result(result['probability'], result['threshold'], {
                **result, 'resampled_from_125hz': True,
                'source_window_start': candidate.get('window_start'),
                'reference_window_start': reference.get('window_start'),
                'domain_warning': 'Research replay target; live single-lead domain'})
        except Exception as exc:
            return self._failure('M4', exc)

    def _m5_predict(self, features, device):
        try:
            if self._m5 is None:
                if hashlib.sha256(self.m5_path.read_bytes()).hexdigest() != M5_SHA256:
                    raise ValueError('M5 SHA-256 mismatch against ml review')
                sys.path.insert(0, str(ROOT / 'security'))
                from m5_network_witness.m5_predict import NetworkWitnessInference
                self._m5 = NetworkWitnessInference(model_path=self.m5_path)
            result = self._m5.predict(device, features)
            if result['status'] != 'active':
                raise ValueError(', '.join(result.get('reasons', ['artifact unavailable'])))
            return self._result(result['network_suspicion_score'], .7, result)
        except Exception as exc:
            return self._failure('M5', exc)
