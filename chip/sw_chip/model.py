"""The stretch 1D-CNN (ml_v2/stretch/cnn_nnpa.py) as a hash-checked live model.

Network definition and input scaling are imported from cnn_nnpa.py itself, so the live
input is built exactly as in training. Weights: chip/model/cnn_state.pt (pinned SHA-256).
Device: the IBM z17 Telum II NNPA ('nnpa', via torch_nnpa) when available, else CPU.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MODEL_DIR = HERE.parent / 'model'
STATE = MODEL_DIR / 'cnn_state.pt'
META = MODEL_DIR / 'cnn_meta.json'
SCRIPT = ROOT / 'ml_v2' / 'stretch' / 'cnn_nnpa.py'
STATE_SHA256 = 'c7ad2efe8dfb475619e336d437e1d4df4aaa3290470bec777f9a4894a571f1c6'
MODEL_NAME = 'M2-cnn-nnpa-2026-10-17'
N = 1250


def _load_script(path):
    spec = importlib.util.spec_from_file_location('sw_chip_cnn_nnpa', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _series(values):
    if values is None:
        return np.full(N, np.nan, dtype=np.float32), False
    x = np.array([np.nan if v is None else v for v in values], dtype=np.float32)
    if x.size != N:
        raise ValueError(f'window must have {N} samples, got {x.size}')
    return x, True


def pick_device(want=None):
    """'nnpa' if torch_nnpa reports the accelerator (unless want='cpu'), else 'cpu'."""
    if want == 'cpu':
        return 'cpu'
    try:
        import torch
        import torch_nnpa  # noqa: F401  registers the 'nnpa' device
        if torch.nnpa.is_available():
            return 'nnpa'
    except Exception:
        pass
    if want == 'nnpa':
        raise RuntimeError('NNPA requested but torch_nnpa / the accelerator is not available')
    return 'cpu'


class ChipModel:
    def __init__(self, device=None, state=STATE, meta=META, script=SCRIPT, sha256=STATE_SHA256):
        import torch
        self.torch = torch
        blob = Path(state).read_bytes()
        digest = hashlib.sha256(blob).hexdigest()
        if digest != sha256:
            raise ValueError(f'cnn_state.pt SHA-256 {digest} != pinned {sha256}')
        self.meta = json.loads(Path(meta).read_text())
        self.thresholds = {k: float(v) for k, v in self.meta['thresholds'].items()}
        self.mod = _load_script(script)
        net = self.mod.Net()
        import io
        net.load_state_dict(torch.load(io.BytesIO(blob), map_location='cpu', weights_only=True))
        net.eval()
        self.device_kind = pick_device(device or os.environ.get('SW_CHIP_DEVICE') or None)
        self.net = net.to(self.device_kind)
        self.device = str(next(self.net.parameters()).device)
        self.sha256 = digest

    def window_arrays(self, window, code):
        d = {}
        for k in ('ecg', 'ppg', 'abp'):
            x, has = _series(window.get(k))
            d[k] = x[None, :]
            d['has_' + k] = np.array([has])
        d['code'] = np.array([code])
        return d

    def predict(self, window, code):
        """Return (p_real, latency_ms): input scaling + forward pass on the model device."""
        if code not in self.thresholds:
            raise ValueError(f'no threshold for alarm {code}')
        torch = self.torch
        t0 = time.perf_counter()
        x, a = self.mod.tensors(self.window_arrays(window, code))
        x, a = x.float(), a.float()       # numpy < 2 promotes the scaling to float64
        with torch.no_grad():
            p = torch.sigmoid(self.net(x.to(self.device_kind), a.to(self.device_kind))).to('cpu')
        p = float(p.numpy().astype(np.float64)[0])
        ms = (time.perf_counter() - t0) * 1000
        if not 0 <= p <= 1:
            raise ValueError('model returned an invalid probability')
        return p, ms

    def message(self, bed_id, ts, code, window):
        p, ms = self.predict(window, code)
        th = self.thresholds[code]
        return {'v': 1, 'bed_id': bed_id, 'ts': int(ts), 'alarm_code': code, 'p_real': round(p, 4),
                'label': 'real' if p >= th else 'false', 'threshold': round(th, 4), 'model': MODEL_NAME,
                'device': self.device, 'latency_ms': round(ms, 2),
                'heldout_challenge_cinc': round(self.meta['heldout_challenge_cinc'], 3),
                'heldout_challenge_vtac': round(self.meta['heldout_challenge_vtac'], 3)}
