"""Portable gradient-boosted trees: export sklearn HistGradientBoostingClassifier to JSON,
predict with numpy only.

Why: the model is trained natively on LinuxONE (big-endian s390x, sklearn 1.4.1). A pickle
of HGB's internal node arrays is tied to that sklearn version and byte order; this JSON
holds only feature index, threshold, NaN direction, children and leaf value per node, so
the brain needs no sklearn and the artifact can be hash-checked before it is parsed.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np


def export_hgb(clf, feature_names, extra):
    """Serialise a fitted binary HistGradientBoostingClassifier (no categorical features)."""
    if getattr(clf, 'n_trees_per_iteration_', 1) != 1:
        raise ValueError('binary classifier expected')
    trees = []
    for (pred,) in clf._predictors:
        nd = pred.nodes
        if np.any(nd['is_categorical']):
            raise ValueError('categorical splits are not supported')
        trees.append({
            'feature': nd['feature_idx'].astype(int).tolist(),
            'threshold': [float(v) for v in nd['num_threshold']],
            'missing_left': nd['missing_go_to_left'].astype(int).tolist(),
            'left': nd['left'].astype(int).tolist(),
            'right': nd['right'].astype(int).tolist(),
            'leaf': nd['is_leaf'].astype(int).tolist(),
            'value': [float(v) for v in nd['value']],
        })
    return {'format': 'sentinelward-gbt-json-1', 'feature_names': list(feature_names),
            'baseline': float(np.ravel(clf._baseline_prediction)[0]), 'trees': trees, **extra}


class PortableGBT:
    def __init__(self, spec):
        if spec.get('format') != 'sentinelward-gbt-json-1':
            raise ValueError('unknown model format')
        self.spec = spec
        self.names = spec['feature_names']
        self.baseline = float(spec['baseline'])
        self.trees = [{k: np.asarray(v) for k, v in t.items()} for t in spec['trees']]

    @classmethod
    def load(cls, path, sha256=None):
        raw = Path(path).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if sha256 is not None and digest != sha256:
            raise ValueError('M2 model SHA-256 mismatch')
        return cls(json.loads(raw))

    def raw_score(self, x):
        x = np.asarray(x, dtype=np.float64)
        total = self.baseline
        for t in self.trees:
            i = 0
            feat, thr, ml, left, right, leaf = t['feature'], t['threshold'], t['missing_left'], t['left'], t['right'], t['leaf']
            while not leaf[i]:
                v = x[feat[i]]
                if v != v:                      # NaN
                    i = left[i] if ml[i] else right[i]
                else:
                    i = left[i] if v <= thr[i] else right[i]
            total += float(t['value'][i])
        return total

    def predict_proba(self, x):
        z = self.raw_score(x)
        return 1.0 / (1.0 + math.exp(-z)) if z > -700 else 0.0
