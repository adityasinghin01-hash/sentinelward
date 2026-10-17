"""Train and evaluate M2 v2 on LinuxONE.

    OMP_NUM_THREADS=2 nice -n 15 python -m m2gbt.train windows.npz outdir/

1. Features for every window (same code as live).
2. Lock the held-out test set first: CinC 2015 = 25% stratified by alarm type x label
   (seed 20261017); VTaC = its official 'test' split (no record in two parts).
3. Grouped 5-fold CV on the rest (groups = record id; VTaC records are patient
   waveform records), picking variant + hyper-parameters by the 2015 challenge score.
4. Per-alarm-type thresholds from the out-of-fold scores of the CinC development set.
5. Refit on all development data, evaluate ONCE on the held-out set (with CIs), compare
   with the live rule, export the portable JSON model, check parity with sklearn.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import os
import platform
import sys
import time
from pathlib import Path

import numpy as np

from . import ALARM_TYPES, MODEL_VERSION
from .features import feature_names, vector, window_features
from .metrics import best_threshold, bootstrap, summary
from .model import PortableGBT, export_hgb

SEED = 20261017


def featurize(d):
    rows = []
    for i in range(d['label'].size):
        g = lambda k: d[k][i] if d['has_' + k][i] else None
        rows.append(window_features(g('ecg'), g('ppg'), g('abp'), str(d['code'][i]), ecg2=d['ecg2'][i]))
    names2 = feature_names(two_lead=True)
    return np.array([vector(r, names2) for r in rows]), names2


def live_rule(d, i):
    """The brain's live ECG rule (sw_brain.detectors) on the same pre-alarm window."""
    from sw_brain.detectors import pulse_metrics
    ecg = [None if not np.isfinite(v) else float(v) for v in d['ecg'][i]] if d['has_ecg'][i] else [None] * 1250
    m = pulse_metrics({'ecg': ecg})
    code = str(d['code'][i])
    if m is None:
        return None
    rate, width, reg = m['rate'], m['qrs_ms'], m['regularity']
    return {'ASYSTOLE': rate < 20, 'BRADY': rate < 40, 'TACHY': rate > 140,
            'VTACH': rate > 100 and width is not None and width >= 100 and reg is not None and reg < .25,
            'VFIB': reg is not None and reg > .35 and rate > 100}[code]


def make_clf(cfg):
    from sklearn.ensemble import HistGradientBoostingClassifier
    return HistGradientBoostingClassifier(learning_rate=cfg['lr'], max_leaf_nodes=cfg['leaves'],
                                          min_samples_leaf=cfg['min_leaf'], max_iter=cfg['iters'],
                                          l2_regularization=1.0, early_stopping=False, random_state=SEED)


def tuned_score(y, s, codes, mask):
    """Challenge score on rows in mask with per-type thresholds tuned on those rows."""
    pred = np.zeros(y.size, bool); th = {}
    for c in ALARM_TYPES:
        m = mask & (codes == c)
        if m.sum() == 0:
            continue
        th[c], _ = best_threshold(y[m], s[m])
        pred[m] = s[m] >= th[c]
    sm = summary(y[mask], s[mask], pred[mask])
    return sm['score'], th


def main(windows, out):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    with np.load(windows) as z:
        d = {k: z[k] for k in z.files}
    y = d['label'].astype(bool); codes = d['code'].astype(str); src = d['source'].astype(str)
    groups = np.char.add(np.char.add(src, ':'), d['record'].astype(str))
    X2, names2 = featurize(d)
    names1 = feature_names(two_lead=False)
    idx1 = [names2.index(n) for n in names1]
    X1 = X2[:, idx1]
    print('features', X2.shape, f'{time.time() - t0:.0f}s', flush=True)
    np.savez_compressed(out / 'features.npz', X2=X2, names2=np.array(names2), y=y, codes=codes, src=src, groups=groups)

    # ---- held-out set, fixed before any model is fitted
    from sklearn.model_selection import StratifiedGroupKFold, train_test_split
    cinc = src == 'cinc2015'; vtac = src == 'vtac'
    hold = np.zeros(y.size, bool)
    ci = np.flatnonzero(cinc)
    strata = np.char.add(codes[ci], y[ci].astype(str))
    _, test_i = train_test_split(ci, test_size=0.25, stratify=strata, random_state=SEED)
    hold[test_i] = True
    hold[vtac & (d['split'].astype(str) == 'test')] = True
    dev = ~hold
    assert not set(groups[hold]) & set(groups[dev]), 'group leak between dev and held-out'
    np.save(out / 'heldout_mask.npy', hold)

    # ---- grouped CV on development data
    dev_i = np.flatnonzero(dev)
    folds = list(StratifiedGroupKFold(5, shuffle=True, random_state=SEED).split(
        dev_i, np.char.add(np.char.add(src[dev_i], codes[dev_i]), y[dev_i].astype(str)), groups[dev_i]))
    for tr, va in folds:
        assert not set(groups[dev_i[tr]]) & set(groups[dev_i[va]])
    grid = [dict(lr=lr, leaves=lv, min_leaf=ml, iters=it) for lr, lv, ml, it in
            itertools.product((0.05, 0.1), (15, 31), (10, 30), (200, 400))]
    variants = {'cinc_only': (None, 1.0), 'pooled_w1': ('all', 1.0), 'pooled_w3': ('all', 3.0)}
    if os.environ.get('M2_QUICK'):          # smoke test of the pipeline only
        grid, variants = grid[:1], {'pooled_w1': ('all', 1.0)}
    cv = []
    for (vname, (use, w)), cfg in itertools.product(variants.items(), grid):
        oof = np.full(y.size, np.nan)
        for tr, va in folds:
            tri, vai = dev_i[tr], dev_i[va]
            if use is None:
                tri = tri[cinc[tri]]
            sw = np.where(cinc[tri], w, 1.0)
            clf = make_clf(cfg).fit(X1[tri], y[tri], sample_weight=sw)
            oof[vai] = clf.predict_proba(X1[vai])[:, 1]
        sc_cinc, _ = tuned_score(y, oof, codes, dev & cinc)
        sc_vtac, _ = tuned_score(y, oof, codes, dev & vtac)
        cv.append({'variant': vname, **cfg, 'cv_score_cinc': sc_cinc, 'cv_score_vtac': sc_vtac})
        print(json.dumps(cv[-1]), f'{time.time() - t0:.0f}s', flush=True)
        np.save(out / f'oof_{vname}_{cfg["lr"]}_{cfg["leaves"]}_{cfg["min_leaf"]}_{cfg["iters"]}.npy', oof)
    json.dump(cv, open(out / 'cv.json', 'w'), indent=1)
    best = max(cv, key=lambda r: (r['cv_score_cinc'], r['cv_score_vtac']))
    cfg = {k: best[k] for k in ('lr', 'leaves', 'min_leaf', 'iters')}
    use, w = variants[best['variant']]
    oof = np.load(out / f'oof_{best["variant"]}_{cfg["lr"]}_{cfg["leaves"]}_{cfg["min_leaf"]}_{cfg["iters"]}.npy')
    _, thresholds = tuned_score(y, oof, codes, dev & cinc)
    print('BEST', best, thresholds, flush=True)

    # ---- final fit on all development data, evaluate once on held-out
    def fit(X):
        tri = dev_i if use is not None else dev_i[cinc[dev_i]]
        return make_clf(cfg).fit(X[tri], y[tri], sample_weight=np.where(cinc[tri], w, 1.0))
    clf = fit(X1)
    s = clf.predict_proba(X1)[:, 1]
    pred = np.array([s[i] >= thresholds.get(codes[i], .5) for i in range(y.size)])

    clf2 = fit(X2)                                    # research comparison: 2 ECG leads
    oof2 = np.full(y.size, np.nan)
    for tr, va in folds:
        tri = dev_i[tr] if use is not None else dev_i[tr][cinc[dev_i[tr]]]
        oof2[dev_i[va]] = make_clf(cfg).fit(X2[tri], y[tri], sample_weight=np.where(cinc[tri], w, 1.0)).predict_proba(X2[dev_i[va]])[:, 1]
    _, thresholds2 = tuned_score(y, oof2, codes, dev & cinc)
    s2 = clf2.predict_proba(X2)[:, 1]
    pred2 = np.array([s2[i] >= thresholds2.get(codes[i], .5) for i in range(y.size)])

    rule = np.array([live_rule(d, i) for i in range(y.size)], dtype=object)
    rule_pred = np.array([bool(r) for r in rule])     # unavailable -> not confirmed

    def block(mask, score, p):
        m = summary(y[mask], score[mask], p[mask])
        m['CI95'] = bootstrap(y[mask], score[mask], p[mask], groups[mask])
        return m
    heldout = {}
    for name, base in (('cinc2015', cinc), ('vtac', vtac)):
        for c in ALARM_TYPES + ('ALL',):
            m = hold & base & ((codes == c) if c != 'ALL' else True)
            if m.sum() == 0:
                continue
            heldout[f'{name}/{c}'] = {'gbt': block(m, s, pred), 'gbt_2lead': block(m, s2, pred2),
                                      'live_rule': block(m, rule_pred.astype(float), rule_pred)}
    # ---- export + parity
    spec = export_hgb(clf, names1, {
        'model_version': MODEL_VERSION, 'thresholds': thresholds, 'config': cfg, 'variant': best['variant'],
        'trained_on': {'host': platform.node(), 'machine': platform.machine(), 'python': platform.python_version(),
                       'sklearn': __import__('sklearn').__version__, 'byteorder': sys.byteorder},
        'n_train': int(dev.sum() if use is not None else (dev & cinc).sum()), 'seed': SEED})
    path = out / 'm2_gbt_2026-10-17.json'
    path.write_text(json.dumps(spec, separators=(',', ':')))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    portable = PortableGBT.load(path, digest)
    hi = np.flatnonzero(hold)
    diff = max(abs(portable.predict_proba(X1[i]) - s[i]) for i in hi)
    t1 = time.time()
    for i in hi[:200]:
        portable.predict_proba(X1[i])
    per_call_ms = (time.time() - t1) / min(200, hi.size) * 1000
    report = {'counts': {'cinc2015': int(cinc.sum()), 'vtac': int(vtac.sum()),
                         'dev': int(dev.sum()), 'heldout': int(hold.sum()),
                         'heldout_cinc': int((hold & cinc).sum()), 'heldout_vtac': int((hold & vtac).sum()),
                         'dev_true': int(y[dev].sum()), 'heldout_true': int(y[hold].sum())},
              'best_cv': best, 'thresholds': thresholds, 'thresholds_2lead': thresholds2,
              'heldout': heldout, 'sha256': digest, 'parity_max_abs_diff': float(diff),
              'portable_predict_ms': per_call_ms, 'n_features': len(names1), 'n_trees': len(spec['trees']),
              'elapsed_s': time.time() - t0, 'host': platform.node(), 'machine': platform.machine()}
    json.dump(report, open(out / 'heldout.json', 'w'), indent=1)
    np.savez(out / 'heldout_scores.npz', s=s, s2=s2, pred=pred, hold=hold, y=y, codes=codes, src=src, groups=groups)
    print(json.dumps({k: report[k] for k in ('counts', 'best_cv', 'thresholds', 'sha256', 'parity_max_abs_diff', 'portable_predict_ms')}))
    for k, v in heldout.items():
        print(k, {m: (round(v[m]['score'], 3), round(v[m]['TPR'], 3), round(v[m]['TNR'], 3), round(v[m]['AUROC'], 3) if v[m]['AUROC'] == v[m]['AUROC'] else None) for m in v})


if __name__ == '__main__':
    os.environ.setdefault('OMP_NUM_THREADS', '2')
    main(sys.argv[1], sys.argv[2])
