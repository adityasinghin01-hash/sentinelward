"""Stretch: small 1D-CNN on the same 10 s pre-alarm windows, inference on the IBM z17 NNPA.

Runs inside IBM's lab container (`notebook`, /opt/venv: torch 2.11 + torch_nnpa 1.5.0).
Training is on CPU (fp32); the trained network is then moved to the 'nnpa' device for
inference and its outputs are compared with the CPU outputs. Same held-out mask as the
tree (written by m2gbt.train); validation = 1/5 of development records (grouped by
record), used for early stopping and per-alarm-type thresholds.

    python cnn_nnpa.py windows.npz heldout_mask.npy out.json
"""
from __future__ import annotations

import hashlib
import json
import sys
import time

import numpy as np
import torch
from torch import nn

TYPES = ('ASYSTOLE', 'BRADY', 'TACHY', 'VFIB', 'VTACH')
SEED = 20261017


def challenge(y, p):
    tp = int(np.sum(y & p)); tn = int(np.sum(~y & ~p)); fp = int(np.sum(~y & p)); fn = int(np.sum(y & ~p))
    d = tp + tn + fp + 5 * fn
    return (tp + tn) / d if d else float('nan'), tp, tn, fp, fn


def auroc(y, s):
    pos, neg = s[y], s[~y]
    if not pos.size or not neg.size:
        return float('nan')
    return float((pos[:, None] > neg[None, :]).mean() + 0.5 * (pos[:, None] == neg[None, :]).mean())


def best_threshold(y, s):
    c = np.unique(np.concatenate([[0.0], s])); best, k = -1, 0
    for i, t in enumerate(c):
        sc = challenge(y, s >= t)[0]
        if sc > best + 1e-12:
            best, k = sc, i
    return float(c[k] if k == 0 else (c[k] + c[k - 1]) / 2)


def tensors(d):
    """6 x 1250: robust-scaled ECG/PPG/ABP (missing -> 0) + their observed masks."""
    chans = []
    for k in ('ecg', 'ppg', 'abp'):
        x = d[k].astype(np.float32).copy()
        x[~d['has_' + k]] = np.nan
        m = np.isfinite(x)
        med = np.nanmedian(np.where(m, x, np.nan), axis=1, keepdims=True)
        iqr = np.nanpercentile(x, 75, axis=1, keepdims=True) - np.nanpercentile(x, 25, axis=1, keepdims=True)
        z = (x - np.nan_to_num(med)) / (np.nan_to_num(iqr) + 1e-3)
        z = np.clip(np.nan_to_num(z, nan=0.0), -20, 20)
        chans += [z, m.astype(np.float32)]
    sig = np.stack(chans, 1)
    onehot = np.stack([(d['code'] == t).astype(np.float32) for t in TYPES], 1)
    return torch.from_numpy(sig), torch.from_numpy(onehot)


class Net(nn.Module):
    def __init__(self):
        super().__init__()
        def block(i, o, k):
            return nn.Sequential(nn.Conv1d(i, o, k, stride=2, padding=k // 2), nn.BatchNorm1d(o), nn.ReLU())
        self.conv = nn.Sequential(block(6, 16, 7), block(16, 32, 7), block(32, 48, 5), block(48, 64, 5), block(64, 64, 3))
        self.head = nn.Sequential(nn.Linear(128 + 5, 32), nn.ReLU(), nn.Dropout(0.2), nn.Linear(32, 1))

    def forward(self, x, a):
        h = self.conv(x)
        h = torch.cat([h.mean(-1), h.amax(-1), a], 1)
        return self.head(h).squeeze(-1)


def main(windows, mask_path, out):
    torch.manual_seed(SEED); np.random.seed(SEED)
    torch.set_num_threads(2)
    with np.load(windows) as z:
        d = {k: z[k] for k in z.files}
    hold = np.load(mask_path)
    y = d['label'].astype(bool); codes = d['code'].astype(str); src = d['source'].astype(str)
    groups = np.char.add(np.char.add(src, ':'), d['record'].astype(str))
    gh = np.array([int(hashlib.sha256(g.encode()).hexdigest(), 16) % 5 for g in groups])
    val = ~hold & (gh == 0); tr = ~hold & ~val
    X, A = tensors(d); Y = torch.from_numpy(y.astype(np.float32))
    net = Net(); opt = torch.optim.AdamW(net.parameters(), 1e-3, weight_decay=1e-3)
    w = torch.where(torch.from_numpy(src == 'cinc2015'), 3.0, 1.0)
    lossf = nn.BCEWithLogitsLoss(reduction='none')
    tri = np.flatnonzero(tr); best = (1e9, None, 0); t0 = time.time(); log = []

    def predict(model, idx, device='cpu', bs=256):
        model.eval(); outs = []
        with torch.no_grad():
            for i in range(0, len(idx), bs):
                j = idx[i:i + bs]
                outs.append(torch.sigmoid(model(X[j].to(device), A[j].to(device))).to('cpu'))
        return torch.cat(outs).numpy().astype(np.float64)

    vi = np.flatnonzero(val)
    for epoch in range(30):
        net.train(); np.random.shuffle(tri)
        for i in range(0, tri.size, 64):
            j = tri[i:i + 64]
            xb = X[j] * (1 + 0.1 * torch.randn(len(j), 1, 1))        # amplitude jitter
            loss = (lossf(net(xb, A[j]), Y[j]) * w[j]).mean()
            opt.zero_grad(); loss.backward(); opt.step()
        pv = predict(net, vi)
        vl = float(np.mean(-(y[vi] * np.log(pv + 1e-7) + (~y[vi]) * np.log(1 - pv + 1e-7))))
        log.append({'epoch': epoch, 'val_loss': vl, 'val_auroc': auroc(y[vi], pv), 's': round(time.time() - t0)})
        print(log[-1], flush=True)
        if vl < best[0]:
            best = (vl, {k: v.clone() for k, v in net.state_dict().items()}, epoch)
        elif epoch - best[2] >= 6:
            break
    net.load_state_dict(best[1])
    pv = predict(net, vi)
    th = {}
    for c in TYPES:
        m = (codes[vi] == c) & (src[vi] == 'cinc2015')
        th[c] = best_threshold(y[vi][m], pv[m]) if m.any() else 0.5
    hi = np.flatnonzero(hold)
    t1 = time.time(); p_cpu = predict(net, hi); cpu_s = time.time() - t1
    nnpa = {'available': False}
    try:
        import torch_nnpa  # noqa: F401  registers the 'nnpa' device
        nnpa['available'] = bool(torch.nnpa.is_available())
        nnpa['telum2'] = bool(torch.nnpa.is_telum2_available())
        dev_net = Net(); dev_net.load_state_dict(best[1]); dev_net.eval(); dev_net = dev_net.to('nnpa')
        t1 = time.time(); p_nnpa = predict(dev_net, hi, device='nnpa'); nnpa['seconds'] = time.time() - t1
        nnpa['max_abs_diff_vs_cpu'] = float(np.max(np.abs(p_nnpa - p_cpu)))
        nnpa['param_device'] = str(next(dev_net.parameters()).device)
    except Exception as exc:
        nnpa['error'] = f'{type(exc).__name__}: {exc}'[:400]
    res = {'best_epoch': best[2], 'log': log, 'thresholds': th, 'cpu_seconds_heldout': cpu_s, 'nnpa': nnpa,
           'n_train': int(tr.sum()), 'n_val': int(val.sum()), 'n_heldout': int(hold.sum()), 'heldout': {}}
    for name in ('cinc2015', 'vtac'):
        for c in TYPES + ('ALL',):
            m = (src[hi] == name) & ((codes[hi] == c) if c != 'ALL' else True)
            if not m.any():
                continue
            pred = np.array([p_cpu[k] >= th[codes[hi][k]] for k in np.flatnonzero(m)])
            sc, tp, tn, fp, fn = challenge(y[hi][m], pred)
            res['heldout'][f'{name}/{c}'] = {'n': int(m.sum()), 'score': sc, 'TP': tp, 'TN': tn, 'FP': fp, 'FN': fn,
                                             'TPR': tp / (tp + fn) if tp + fn else None, 'TNR': tn / (tn + fp) if tn + fp else None,
                                             'AUROC': auroc(y[hi][m], p_cpu[m])}
    json.dump(res, open(out, 'w'), indent=1)
    np.save(out.replace('.json', '_scores.npy'), p_cpu)
    print(json.dumps({k: res[k] for k in ('best_epoch', 'thresholds', 'nnpa', 'cpu_seconds_heldout')}))
    for k, v in res['heldout'].items():
        print(k, {m: (round(v[m], 3) if isinstance(v[m], float) else v[m]) for m in v})


if __name__ == '__main__':
    main(*sys.argv[1:4])
