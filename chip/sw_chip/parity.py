"""Live-path parity and per-alarm latency on the 670 held-out windows.

Each held-out window is turned into the live window dict (lists, None for missing samples,
abp None when absent) and scored one at a time through ChipModel.predict, exactly like a live
alarm. Scores are compared with the training run's CPU batch scores (cnn_result_scores.npy).

    python -m sw_chip.parity windows.npz heldout_mask.npy scores.npy out.json [--device nnpa|cpu]
"""
from __future__ import annotations

import argparse
import json
import statistics

import numpy as np


def live_window(d, i):
    w = {}
    for k in ('ecg', 'ppg', 'abp'):
        if not d['has_' + k][i]:
            w[k] = None
            continue
        x = d[k][i].astype(np.float64)
        w[k] = [None if not np.isfinite(v) else float(v) for v in x]
    return w


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('windows'); ap.add_argument('mask'); ap.add_argument('scores'); ap.add_argument('out')
    ap.add_argument('--device', default=None)
    a = ap.parse_args(argv)
    import torch
    torch.set_num_threads(1)
    from .bench import pct
    from .model import ChipModel
    model = ChipModel(device=a.device)
    with np.load(a.windows) as z:
        d = {k: z[k] for k in z.files}
    hi = np.flatnonzero(np.load(a.mask))
    ref = np.load(a.scores)
    codes = d['code'].astype(str)
    for _ in range(3):
        model.predict(live_window(d, hi[0]), codes[hi[0]])
    p, lat = [], []
    for i in hi:
        s, ms = model.predict(live_window(d, i), codes[i])
        p.append(s); lat.append(ms)
    p = np.array(p)
    diff = np.abs(p - ref)
    agree = np.mean([(p[k] >= model.thresholds[codes[i]]) == (ref[k] >= model.thresholds[codes[i]])
                     for k, i in enumerate(hi)])
    res = {'device': model.device, 'n': int(hi.size), 'max_abs_diff_vs_training_cpu': float(diff.max()),
           'mean_abs_diff': float(diff.mean()), 'label_agreement': float(agree),
           'latency_ms': {'n': len(lat), 'median': statistics.median(lat), 'p95': pct(lat, 95), 'max': max(lat)}}
    json.dump(res, open(a.out, 'w'), indent=1)
    print(json.dumps(res))


if __name__ == '__main__':
    main()
