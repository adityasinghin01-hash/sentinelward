"""M2 v2 adapter: gradient-boosted trees trained on LinuxONE (ml_v2/), hash-checked.

Explains a monitor alarm with P(real) from the full 10 s pre-alarm window. It never
suppresses, delays or downgrades the alarm: the decision layer keeps EMERGENCY for
the whole alarm hold regardless of this score. Any failure returns 'unavailable' and the
caller falls back to the live rule.
"""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
_ML_V2 = ROOT / 'ml_v2'
ARTIFACT = _ML_V2 / 'artifacts' / 'm2_gbt_2026-10-17.json'
# Pinned digest of the artifact written by ml_v2/m2gbt/train.py on the LinuxONE build server.
SHA256 = 'cc59fc616e67d8b2bfebfb8263b9ea81f54492201fdb368d7d85ecc5c3802348'
MODEL_VERSION = 'M2-gbt-2026-10-17'


class GbtM2:
    def __init__(self, path=ARTIFACT, sha256=SHA256, model=None):
        self.path, self.sha256 = Path(path), sha256
        self._model = model
        self._cache = {}
        self.failure = None

    def reset(self):
        self._cache.clear()

    def _load(self):
        if self._model is None:
            if str(_ML_V2) not in sys.path:
                sys.path.insert(0, str(_ML_V2))
            from m2gbt.model import PortableGBT
            self._model = PortableGBT.load(self.path, self.sha256)   # hash before parse
        return self._model

    def evaluate(self, window, code):
        key = (window.get('bed_id'), window.get('window_start'), code)
        if key in self._cache:
            return self._cache[key]
        try:
            model = self._load()
            if str(_ML_V2) not in sys.path:
                sys.path.insert(0, str(_ML_V2))
            from m2gbt.features import vector, window_features
            thresholds = model.spec['thresholds']
            if code not in thresholds:
                raise ValueError(f'no threshold for alarm {code}')
            ecg = window.get('ecg')
            if ecg is None or sum(v is not None for v in ecg) < .5 * len(ecg):
                raise ValueError('pre-alarm ECG mostly missing')
            feats = window_features(ecg, window.get('ppg'), window.get('abp'), code)
            score = float(model.predict_proba(vector(feats, model.names)))
            threshold = float(thresholds[code])
            if not 0 <= score <= 1:
                raise ValueError('model returned an invalid probability')
            pick = lambda k: None if feats[k] != feats[k] else round(float(feats[k]), 3)
            out = {'status': 'active', 'score': score, 'threshold': threshold, 'positive': score >= threshold,
                   'extra': {'ecg_hr_bpm': pick('ecg_hr'), 'ecg_longest_gap_s': pick('ecg_maxgap'),
                             'pulse_hr_bpm': pick('pulse_hr_best'), 'qrs_width_ms': pick('ecg_qrsw'),
                             'vf_band_fraction': pick('ecg_vfband'), 'abp_mean_mmhg': pick('abp_mean'),
                             'source_window_start': window.get('window_start')}}
        except Exception as exc:
            self.failure = f'{type(exc).__name__}: {exc}'[:240]
            out = {'status': 'unavailable', 'extra': {'unavailable_reason': self.failure}}
        if len(self._cache) > 256:
            self._cache.clear()
        self._cache[key] = out
        return out
