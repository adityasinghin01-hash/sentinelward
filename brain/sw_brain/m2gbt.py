"""M2 v2 adapter: gradient-boosted trees trained on LinuxONE (ml_v2/), hash-checked.

Explains a monitor alarm with P(real) from the full 10 s pre-alarm window. It never
suppresses, delays or downgrades the alarm: the decision layer keeps EMERGENCY for
the whole alarm hold regardless of this score. Any failure returns 'unavailable' and the
caller falls back to the live rule.

doc 00 v1.3: when the pre-alarm window carries a second ECG lead (``ecg2``, at least half of
its samples present) the 2-lead model ``M2-gbt2-2026-10-17`` runs; otherwise, or if that
artifact fails its hash, the 1-lead model ``M2-gbt-2026-10-17`` runs.
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
# 2-lead model written by ml_v2/m2gbt/train2.py on the LinuxONE build server.
ARTIFACT_2 = _ML_V2 / 'artifacts' / 'm2_gbt2_2026-10-17.json'
SHA256_2 = '72daa84b4aac9d15c8656595592e76b6e8fa030e613869e1967616522ae52f75'
MODEL_VERSION_2 = 'M2-gbt2-2026-10-17'
MIN_PRESENT = .5        # a lead counts as present with at least half of its samples


def _present(values):
    return values is not None and len(values) > 0 and sum(v is not None for v in values) >= MIN_PRESENT * len(values)


class GbtM2:
    def __init__(self, path=ARTIFACT, sha256=SHA256, model=None, path2=ARTIFACT_2, sha256_2=SHA256_2, model2=None):
        self.path, self.sha256 = Path(path), sha256
        self.path2, self.sha256_2 = (Path(path2) if path2 is not None else None), sha256_2
        self._model, self._model2 = model, model2
        self._cache = {}
        self.failure = None
        self.failure_2lead = None

    def reset(self):
        self._cache.clear()

    @staticmethod
    def _import():
        if str(_ML_V2) not in sys.path:
            sys.path.insert(0, str(_ML_V2))

    def _load(self):
        if self._model is None:
            self._import()
            from m2gbt.model import PortableGBT
            self._model = PortableGBT.load(self.path, self.sha256)   # hash before parse
        return self._model

    def _load2(self):
        if self._model2 is None:
            if self.path2 is None:
                raise ValueError('no 2-lead artifact configured')
            self._import()
            from m2gbt.model import PortableGBT
            self._model2 = PortableGBT.load(self.path2, self.sha256_2)   # hash before parse
        return self._model2

    def evaluate(self, window, code):
        two = _present(window.get('ecg2'))
        key = (window.get('bed_id'), window.get('window_start'), code, two)
        if key in self._cache:
            return self._cache[key]
        try:
            self._import()
            from m2gbt.features import vector, window_features
            ecg = window.get('ecg')
            if not _present(ecg):
                raise ValueError('pre-alarm ECG mostly missing')
            model, version, leads, fallback = None, MODEL_VERSION, 1, None
            if two:
                try:
                    model, version, leads = self._load2(), MODEL_VERSION_2, 2
                except Exception as exc:     # 2-lead artifact unusable: the 1-lead model still explains
                    self.failure_2lead = fallback = f'{type(exc).__name__}: {exc}'[:240]
            if model is None:
                model = self._load()
            thresholds = model.spec['thresholds']
            if code not in thresholds:
                raise ValueError(f'no threshold for alarm {code}')
            feats = window_features(ecg, window.get('ppg'), window.get('abp'), code,
                                    ecg2=window.get('ecg2') if leads == 2 else None)
            score = float(model.predict_proba(vector(feats, model.names)))
            threshold = float(thresholds[code])
            if not 0 <= score <= 1:
                raise ValueError('model returned an invalid probability')
            pick = lambda k: None if k not in feats or feats[k] != feats[k] else round(float(feats[k]), 3)
            extra = {'ecg_hr_bpm': pick('ecg_hr'), 'ecg_longest_gap_s': pick('ecg_maxgap'),
                     'pulse_hr_bpm': pick('pulse_hr_best'), 'qrs_width_ms': pick('ecg_qrsw'),
                     'vf_band_fraction': pick('ecg_vfband'), 'abp_mean_mmhg': pick('abp_mean'),
                     'source_window_start': window.get('window_start'), 'ecg_leads_used': leads}
            if leads == 2:
                extra.update(ecg2_hr_bpm=pick('ecg2_hr'), ecg2_longest_gap_s=pick('ecg2_maxgap'),
                             ecg_lead_names=window.get('ecg_leads'))
            if fallback:
                extra['two_lead_unavailable_reason'] = fallback
            out = {'status': 'active', 'score': score, 'threshold': threshold, 'positive': score >= threshold,
                   'model_version': version, 'extra': extra}
        except Exception as exc:
            self.failure = f'{type(exc).__name__}: {exc}'[:240]
            out = {'status': 'unavailable', 'extra': {'unavailable_reason': self.failure}}
        if len(self._cache) > 256:
            self._cache.clear()
        self._cache[key] = out
        return out
