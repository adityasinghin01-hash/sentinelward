"""Optional M2 bundle inference, written 2026-10-17. Never waits on scoring."""
from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import pickle
import re
import sys

import numpy as np

MODEL_VERSION = 'M2-gbt-2026-10-17'


def _feature_module(model_path, configured_path):
    """Load the new feature package without changing the global import path."""
    if configured_path:
        path = Path(configured_path).expanduser().resolve()
    else:
        candidates = [model_path.parent / 'features.py']
        candidates += [parent / 'ml_v2' / 'm2gbt' / 'features.py' for parent in model_path.parents]
        path = next((p for p in candidates if p.is_file()), None)
        if path is None:
            raise FileNotFoundError('M2 feature module missing; set SW_M2_FEATURES')
    # A distinct package name supports relative imports and isolates bundle paths.
    package = '_sw_m2_' + hashlib.sha256(str(path.parent).encode()).hexdigest()[:16]
    if package not in sys.modules:
        spec = importlib.util.spec_from_file_location(package, path.parent / '__init__.py',
                                                     submodule_search_locations=[str(path.parent)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[package] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(package, None)
            raise
    name = package + '.features'
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        sys.modules[name] = module
    return sys.modules[name]


def _portable_probability(bundle, values):
    """Evaluate the new export's numeric binary trees on either byte order."""
    total = float(bundle['baseline'])
    for tree in bundle['trees']:
        node = 0
        for _ in range(len(tree['leaf'])):
            if tree['leaf'][node]:
                total += float(tree['value'][node])
                break
            value = values[tree['feature'][node]]
            left = bool(tree['missing_left'][node]) if math.isnan(value) else value <= tree['threshold'][node]
            node = tree['left' if left else 'right'][node]
        else:
            raise ValueError('Cyclic M2 tree')
    if not math.isfinite(total):
        raise ValueError('Nonfinite M2 tree score')
    return 1 / (1 + math.exp(-total)) if total >= 0 else math.exp(total) / (1 + math.exp(total))


class M2Model:
    """One worker, bounded pending requests and cache; foreground calls never wait.

    A pickle bundle is a dict containing model_version, model (binary sklearn
    predict_proba), feature_names, and thresholds keyed by monitor alarm code.
    The new portable JSON export uses the same metadata. Only operator-configured
    bundles are loaded, and their sidecar digest is checked before parsing/imports.
    """

    def __init__(self, path=None, *, features_path=None):
        configured = path if path is not None else os.environ.get('SW_M2_MODEL')
        self.path = Path(configured).expanduser().resolve() if configured else None
        self.features_path = features_path or os.environ.get('SW_M2_FEATURES')
        self.unavailable_reason = 'model_not_configured' if self.path is None else 'model_pending'
        self._executor = None
        self._pending = {}
        self._cache = OrderedDict()
        self._generation = 0
        self._bundle = None
        self._features = None
        self._load_error = None

    def reset(self):
        self._generation += 1
        self._cache.clear()
        # Running tasks retain their generation and cannot enter the new cache.
        for _, future in self._pending.values():
            future.cancel()

    def close(self):
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)

    def score(self, window, alarm_code):
        if self.path is None:
            return None
        for key, (generation, future) in list(self._pending.items()):
            if not future.done():
                continue
            del self._pending[key]
            if generation != self._generation:
                continue
            try:
                self._cache[key] = (future.result(), '')
            except Exception as exc:
                self._cache[key] = (None, f'{type(exc).__name__}: {exc}'[:240])
            while len(self._cache) > 128:
                self._cache.popitem(last=False)
        key = (window['bed_id'], window.get('device_id'), window['window_start'], alarm_code)
        if key in self._cache:
            output, self.unavailable_reason = self._cache[key]
            return output
        if key in self._pending or len(self._pending) >= 12:
            self.unavailable_reason = 'model_busy'
            return None
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='sw-m2')
        self._pending[key] = (self._generation, self._executor.submit(self._predict, deepcopy(window), alarm_code))
        self.unavailable_reason = 'model_pending'
        return None

    def _load(self):
        if self._load_error:
            raise ValueError(self._load_error)
        if self._bundle is not None:
            return
        try:
            raw = self.path.read_bytes()
            sidecar = Path(str(self.path) + '.sha256')
            if not sidecar.exists():
                sidecar = self.path.with_suffix('.sha256')
            expected = sidecar.read_text().split()[0].lower()
            if not re.fullmatch('[0-9a-f]{64}', expected) or hashlib.sha256(raw).hexdigest() != expected:
                raise ValueError('M2 SHA-256 mismatch')
            bundle = json.loads(raw) if self.path.suffix == '.json' else pickle.loads(raw)
            if not isinstance(bundle, dict) or bundle.get('model_version') != MODEL_VERSION:
                raise ValueError('Unexpected M2 model version')
            names = bundle.get('feature_names')
            if not isinstance(names, list) or not names or not all(isinstance(n, str) for n in names) or len(set(names)) != len(names):
                raise ValueError('Invalid M2 feature names')
            features = _feature_module(self.path, self.features_path)
            if getattr(features, 'MODEL_VERSION', MODEL_VERSION) != MODEL_VERSION:
                raise ValueError('Unexpected M2 feature version')
            self._features, self._bundle = features, bundle
        except Exception as exc:
            self._load_error = f'{type(exc).__name__}: {exc}'[:240]
            raise

    def _predict(self, window, alarm_code):
        self._load()
        bundle = self._bundle
        threshold = float(bundle['thresholds'][alarm_code])
        if not math.isfinite(threshold) or not 0 <= threshold <= 1:
            raise ValueError('Invalid M2 threshold')
        if any(window.get(ch) is not None and len(window[ch]) != 1250 for ch in ('ecg', 'ppg', 'abp')):
            raise ValueError('M2 requires 1250 samples per channel')
        features = self._features.window_features(window.get('ecg'), ppg=window.get('ppg'),
                                                  abp=window.get('abp'), alarm_code=alarm_code)
        values = np.array([features[name] for name in bundle['feature_names']], dtype=float)
        if bundle.get('format') == 'sentinelward-gbt-json-1':
            probability = _portable_probability(bundle, values)
        else:
            model = bundle['model']
            classes = list(model.classes_)
            probability = float(model.predict_proba(values.reshape(1, -1))[0][classes.index(1)])
        if not math.isfinite(probability) or not 0 <= probability <= 1:
            raise ValueError('Invalid M2 probability')
        return dict(score=probability, threshold=threshold, positive=probability >= threshold,
                    model_version=MODEL_VERSION, source_window_start=window['window_start'])
