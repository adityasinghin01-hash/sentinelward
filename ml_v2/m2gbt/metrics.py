"""Metrics: 2015 challenge score, TPR/TNR, AUROC, grouped bootstrap confidence intervals."""
from __future__ import annotations

import numpy as np


def counts(y, pred):
    y = np.asarray(y, bool); pred = np.asarray(pred, bool)
    return (int(np.sum(y & pred)), int(np.sum(~y & ~pred)), int(np.sum(~y & pred)), int(np.sum(y & ~pred)))


def challenge_score(y, pred):
    """PhysioNet/CinC 2015: (TP+TN)/(TP+TN+FP+5*FN)."""
    tp, tn, fp, fn = counts(y, pred)
    d = tp + tn + fp + 5 * fn
    return (tp + tn) / d if d else float('nan')


def auroc(y, s):
    y = np.asarray(y, bool); s = np.asarray(s, float)
    pos, neg = s[y], s[~y]
    if pos.size == 0 or neg.size == 0:
        return float('nan')
    # Mann-Whitney U with ties counted as 1/2.
    order = np.argsort(np.concatenate([pos, neg]), kind='mergesort')
    allv = np.concatenate([pos, neg])[order]
    ranks = np.empty(allv.size)
    i = 0
    while i < allv.size:
        j = i
        while j + 1 < allv.size and allv[j + 1] == allv[i]:
            j += 1
        ranks[i:j + 1] = (i + j) / 2 + 1
        i = j + 1
    r = np.empty(allv.size); r[order] = ranks
    return float((r[:pos.size].sum() - pos.size * (pos.size + 1) / 2) / (pos.size * neg.size))


def summary(y, s, pred):
    tp, tn, fp, fn = counts(y, pred)
    return {'n': len(y), 'n_true': int(np.sum(y)), 'TP': tp, 'TN': tn, 'FP': fp, 'FN': fn,
            'TPR': tp / (tp + fn) if tp + fn else float('nan'),
            'TNR': tn / (tn + fp) if tn + fp else float('nan'),
            'score': challenge_score(y, pred), 'AUROC': auroc(y, s)}


def bootstrap(y, s, pred, groups, n=2000, seed=20261017):
    """Percentile 95% CI, resampling whole groups (records/patients)."""
    y, s, pred, groups = map(np.asarray, (y, s, pred, groups))
    rng = np.random.default_rng(seed)
    ug, inv = np.unique(groups, return_inverse=True)
    members = [np.flatnonzero(inv == g) for g in range(ug.size)]
    stats = {k: [] for k in ('TPR', 'TNR', 'score', 'AUROC')}
    for _ in range(n):
        idx = np.concatenate([members[g] for g in rng.integers(0, ug.size, ug.size)])
        m = summary(y[idx], s[idx], pred[idx])
        for k in stats:
            stats[k].append(m[k])
    out = {}
    for k, v in stats.items():
        v = np.asarray(v, float); v = v[np.isfinite(v)]
        out[k] = [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))] if v.size else [float('nan')] * 2
    return out


def best_threshold(y, s):
    """Threshold maximising the challenge score; ties broken toward the lower threshold."""
    y = np.asarray(y, bool); s = np.asarray(s, float)
    cands = np.unique(np.concatenate([[0.0], s]))
    best, best_k = -1.0, 0
    for k, t in enumerate(cands):
        sc = challenge_score(y, s >= t)
        if sc > best + 1e-12:
            best, best_k = sc, k
    # Midpoint to the next lower observed score, so the cut is not on a training point.
    t = cands[best_k] if best_k == 0 else (cands[best_k] + cands[best_k - 1]) / 2
    return float(t), best
