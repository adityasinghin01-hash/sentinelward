"""Export the 2-ECG-lead M2 model (doc 00 v1.3: vitals may carry ecg2).

    OMP_NUM_THREADS=2 nice -n 15 python -m m2gbt.train2 windows.npz out_v1/ out_v2/

Same recipe as m2gbt.train, nothing re-tuned on the held-out set:
* the held-out set is rebuilt with the same seed and must equal out_v1/heldout_mask.npy;
* the configuration is the one grouped CV picked for the 1-lead model (out_v1/heldout.json best_cv);
* per-type thresholds come from out-of-fold scores of the CinC development set (same 5 folds);
* the model is fitted on all development data, exported to portable JSON and checked for parity;
* evaluated once on the held-out set, side by side with the deployed 1-lead artifact.
The 2-lead model is used live only when the pre-alarm window carries ecg2; otherwise the
1-lead model runs, so the 1-lead artifact is not changed here.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import time
from pathlib import Path

import numpy as np

from . import ALARM_TYPES
from .features import feature_names
from .metrics import bootstrap, summary
from .model import PortableGBT, export_hgb
from .train import SEED, featurize, make_clf, tuned_score

MODEL_VERSION_2 = 'M2-gbt2-2026-10-17'
ARTIFACT_1 = Path(__file__).resolve().parents[1] / 'artifacts' / 'm2_gbt_2026-10-17.json'
SHA256_1 = 'cc59fc616e67d8b2bfebfb8263b9ea81f54492201fdb368d7d85ecc5c3802348'
VARIANTS = {'cinc_only': (None, 1.0), 'pooled_w1': ('all', 1.0), 'pooled_w3': ('all', 3.0)}


def main(windows, out_v1, out_v2):
    out_v1, out_v2 = Path(out_v1), Path(out_v2)
    out_v2.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    with np.load(windows) as z:
        d = {k: z[k] for k in z.files}
    y = d['label'].astype(bool); codes = d['code'].astype(str); src = d['source'].astype(str)
    groups = np.char.add(np.char.add(src, ':'), d['record'].astype(str))
    X2, names2 = featurize(d)
    names1 = feature_names(two_lead=False)
    X1 = X2[:, [names2.index(n) for n in names1]]
    has2 = d['has_ecg2'].astype(bool)
    print('features', X2.shape, f'{time.time() - t0:.0f}s', 'with ecg2', int(has2.sum()), flush=True)

    from sklearn.model_selection import StratifiedGroupKFold, train_test_split
    cinc = src == 'cinc2015'; vtac = src == 'vtac'
    hold = np.zeros(y.size, bool)
    ci = np.flatnonzero(cinc)
    _, test_i = train_test_split(ci, test_size=0.25, stratify=np.char.add(codes[ci], y[ci].astype(str)),
                                 random_state=SEED)
    hold[test_i] = True
    hold[vtac & (d['split'].astype(str) == 'test')] = True
    assert np.array_equal(hold, np.load(out_v1 / 'heldout_mask.npy')), 'held-out set differs from the 1-lead run'
    dev = ~hold
    assert not set(groups[hold]) & set(groups[dev]), 'group leak between dev and held-out'
    dev_i = np.flatnonzero(dev)
    folds = list(StratifiedGroupKFold(5, shuffle=True, random_state=SEED).split(
        dev_i, np.char.add(np.char.add(src[dev_i], codes[dev_i]), y[dev_i].astype(str)), groups[dev_i]))

    best = json.load(open(out_v1 / 'heldout.json'))['best_cv']
    cfg = {k: best[k] for k in ('lr', 'leaves', 'min_leaf', 'iters')}
    use, w = VARIANTS[best['variant']]

    def rows(idx):
        return idx if use is not None else idx[cinc[idx]]
    oof2 = np.full(y.size, np.nan)
    for tr, va in folds:
        tri = rows(dev_i[tr])
        clf = make_clf(cfg).fit(X2[tri], y[tri], sample_weight=np.where(cinc[tri], w, 1.0))
        oof2[dev_i[va]] = clf.predict_proba(X2[dev_i[va]])[:, 1]
    cv_cinc, thresholds2 = tuned_score(y, oof2, codes, dev & cinc)
    cv_vtac, _ = tuned_score(y, oof2, codes, dev & vtac)
    print('CV 2-lead', cv_cinc, cv_vtac, thresholds2, flush=True)

    tri = rows(dev_i)
    clf2 = make_clf(cfg).fit(X2[tri], y[tri], sample_weight=np.where(cinc[tri], w, 1.0))
    s2 = clf2.predict_proba(X2)[:, 1]
    pred2 = np.array([s2[i] >= thresholds2.get(codes[i], .5) for i in range(y.size)])

    # Deployed 1-lead artifact on the same rows (what the brain runs when ecg2 is absent).
    m1 = PortableGBT.load(ARTIFACT_1, SHA256_1)
    s1 = np.array([m1.predict_proba(X1[i]) for i in range(y.size)])
    th1 = m1.spec['thresholds']
    pred1 = np.array([s1[i] >= th1[codes[i]] for i in range(y.size)])
    # What the brain does: 2-lead model when the window has ecg2, else the 1-lead model.
    s_live = np.where(has2, s2, s1); pred_live = np.where(has2, pred2, pred1)

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
            heldout[f'{name}/{c}'] = {'gbt_1lead': block(m, s1, pred1), 'gbt_2lead': block(m, s2, pred2),
                                      'brain_rule': block(m, s_live, pred_live), 'n_with_ecg2': int((m & has2).sum())}

    spec = export_hgb(clf2, names2, {
        'model_version': MODEL_VERSION_2, 'thresholds': thresholds2, 'config': cfg, 'variant': best['variant'],
        'leads': 2, 'ecg2_rule': 'lead V, else the next ECG lead (sw_data.dsp.pick_ecg2)',
        'trained_on': {'host': platform.node(), 'machine': platform.machine(), 'python': platform.python_version(),
                       'sklearn': __import__('sklearn').__version__, 'byteorder': sys.byteorder},
        'n_train': int(tri.size), 'seed': SEED})
    path = out_v2 / 'm2_gbt2_2026-10-17.json'
    path.write_text(json.dumps(spec, separators=(',', ':')))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    portable = PortableGBT.load(path, digest)
    hi = np.flatnonzero(hold)
    diff = max(abs(portable.predict_proba(X2[i]) - s2[i]) for i in hi)
    report = {'model_version': MODEL_VERSION_2, 'sha256': digest, 'parity_max_abs_diff': float(diff),
              'config': cfg, 'variant': best['variant'], 'cv_2lead': {'cinc': cv_cinc, 'vtac': cv_vtac},
              'thresholds_2lead': thresholds2, 'thresholds_1lead': th1,
              'counts': {'heldout': int(hold.sum()), 'heldout_with_ecg2': int((hold & has2).sum()),
                         'dev': int(dev.sum()), 'n_train': int(tri.size)},
              'heldout': heldout, 'n_features': len(names2), 'n_trees': len(spec['trees']),
              'elapsed_s': time.time() - t0, 'host': platform.node(), 'machine': platform.machine()}
    json.dump(report, open(out_v2 / 'heldout2.json', 'w'), indent=1)
    np.savez(out_v2 / 'heldout_scores2.npz', s1=s1, s2=s2, pred1=pred1, pred2=pred2, has2=has2, hold=hold, y=y,
             codes=codes, src=src, groups=groups)
    print(json.dumps({k: report[k] for k in ('sha256', 'parity_max_abs_diff', 'counts', 'cv_2lead', 'thresholds_2lead')}))
    for k, v in heldout.items():
        print(k, v['n_with_ecg2'], {m: (round(v[m]['score'], 3), round(v[m]['TPR'], 3), round(v[m]['TNR'], 3),
                                        round(v[m]['AUROC'], 3) if v[m]['AUROC'] == v[m]['AUROC'] else None)
                                    for m in ('gbt_1lead', 'gbt_2lead', 'brain_rule')})


if __name__ == '__main__':
    os.environ.setdefault('OMP_NUM_THREADS', '2')
    main(*sys.argv[1:4])
