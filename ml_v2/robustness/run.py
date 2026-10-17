"""M2 robustness and forged-input evaluation on the locked held-out windows (offline).

    python -m robustness.run <windows_v13.npz> <heldout_mask.npy> <heldout_shift.npz> <out.json> [heldout_scores2.npz]
    (cwd ml_v2/, PYTHONPATH also <repo>/brain and <repo>/common)

What is scored: the brain's real M2 code path, ``sw_brain.detectors.EmergencyDetector`` with the
pinned artifacts (``sw_brain.m2gbt.GbtM2``, SHA-256 checked). It picks the 2-lead model when
``ecg2`` is at least half present, else the 1-lead model, and falls back to the live ECG rule
when the trees cannot run (e.g. ECG mostly missing). If no advice can be given at all, the
alarm simply stands (M2 never suppresses an alarm): such rows are counted as "predicted real"
with score 1.0 and reported in ``paths['none']``.

Data: the 670 held-out windows (188 CinC 2015 records, 482 VTaC events) locked before
training (``out/heldout_mask.npy``), from ``windows_v13.npz`` built by m2gbt.prep. Nothing is
trained or tuned here; thresholds are the deployed per-type ones.

Every perturbation is applied to the 125 Hz window, then rounded like the simulator
(ECG 3, PPG 2, ABP 1 decimals). Random parts use numpy's default_rng seeded from
(SEED, condition index, row index), so the run is reproducible and independent of
process scheduling.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve()
ROOT = HERE.parents[2]
for p in (ROOT / 'ml_v2', ROOT / 'brain', ROOT / 'common'):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from m2gbt import ALARM_TYPES, FS                     # noqa: E402
from m2gbt.metrics import summary                      # noqa: E402
from m2gbt.prep import ROUND                           # noqa: E402

SEED = 20261018
N = 10 * FS
KEYS = ('ecg', 'ecg2', 'ppg', 'abp')
ECGS = ('ecg', 'ecg2')

# name -> (family, strength label, spec)
CONDITIONS = {'clean': ('clean', '-', None)}
for snr in (30, 20, 10):
    CONDITIONS[f'noise_snr{snr}'] = ('white noise, all channels', f'SNR {snr} dB', ('noise', snr))
for a in (0.25, 0.5, 1.0):
    CONDITIONS[f'wander_{a:g}'] = ('baseline wander 0.15-0.5 Hz, ECG + PPG', f'{a:g} x signal range', ('wander', a))
for a in (0.1, 0.25, 0.5):
    CONDITIONS[f'powerline_{a:g}'] = ('powerline 50 Hz, ECG leads', f'{a:g} x signal range', ('mains', a))
for g in (0.25, 0.5, 2.0):
    CONDITIONS[f'gain_{g:g}'] = ('ECG amplitude scaling', f'x{g:g}', ('gain', g))
for ch in ('ecg2', 'ppg', 'abp'):
    for frac in (0.3, 0.6, 1.0):
        CONDITIONS[f'{ch}_drop_{int(frac * 100)}'] = (f'{ch.upper()} dropout (last part of window missing)',
                                                     f'{int(frac * 100)}% missing', ('drop', ch, frac))
for s in (0.5, 1.0, 2.0):
    CONDITIONS[f'shift_{s:g}s'] = ('time shift (window ends s early; rebuilt from source)', f'{s:g} s', ('shift', s))
for L in (1.0, 2.0, 4.0):
    CONDITIONS[f'flatline_{L:g}s'] = ('sample-hold flatline, all channels', f'{L:g} s segment', ('hold', L))
# Forged inputs (step 2): real ECG, pulse channels from elsewhere.
CONDITIONS['forge_pulse_other_patient'] = ('forged: PPG+ABP copied from another patient', 'random donor', ('swap', 'any'))
CONDITIONS['forge_pulse_from_false_alarm'] = ('forged: PPG+ABP copied from a false-alarm window', 'calm donor', ('swap', 'false'))
for s in (2.0, 5.0):
    CONDITIONS[f'forge_pulse_shift_{s:g}s'] = ('forged: own PPG+ABP time-shifted (circular)', f'{s:g} s', ('roll', s))


def _round(key, y):
    return np.round(y, ROUND['ecg' if key == 'ecg2' else key])


def _range(x):
    ok = x[np.isfinite(x)]
    return float(np.percentile(ok, 95) - np.percentile(ok, 5)) if ok.size > 1 else 0.0


def perturb(spec, row, rng, ctx):
    """row: dict key -> float array (NaN = missing) or None. Returns a new dict."""
    out = {k: (None if v is None else v.astype(np.float64).copy()) for k, v in row.items()}
    if spec is None:
        return out
    kind = spec[0]
    t = np.arange(N) / FS
    if kind == 'noise':
        for k in KEYS:
            x = out[k]
            if x is None:
                continue
            ok = np.isfinite(x)
            p = float(np.var(x[ok])) if ok.sum() > 1 else 0.0
            x += rng.normal(0, np.sqrt(p / 10 ** (spec[1] / 10)), N)
    elif kind == 'wander':
        for k in ECGS + ('ppg',):
            x = out[k]
            if x is None:
                continue
            f = rng.uniform(0.15, 0.5, 2); ph = rng.uniform(0, 2 * np.pi, 2)
            # peak amplitude up to spec[1] x the channel's 5-95% range
            x += spec[1] * _range(x) * (np.sin(2 * np.pi * f[0] * t + ph[0]) + np.sin(2 * np.pi * f[1] * t + ph[1])) / 2
    elif kind == 'mains':
        for k in ECGS:
            x = out[k]
            if x is not None:
                x += spec[1] * _range(x) / 2 * np.sin(2 * np.pi * 50 * t + rng.uniform(0, 2 * np.pi))
    elif kind == 'gain':
        for k in ECGS:
            if out[k] is not None:
                out[k] = out[k] * spec[1]
    elif kind == 'drop':
        _, ch, frac = spec
        if out[ch] is not None:
            if frac >= 1:
                out[ch] = None
            else:
                out[ch][int(round(N * (1 - frac))):] = np.nan
    elif kind == 'shift':
        out = {k: (None if v is None else v.astype(np.float64).copy()) for k, v in ctx['shift_row'].items()}
    elif kind == 'hold':
        L = int(spec[1] * FS)
        a = int(rng.integers(0, N - L))
        for k in KEYS:
            if out[k] is not None:
                out[k][a:a + L] = out[k][a]
    elif kind == 'swap':
        donor = ctx['donor']
        out['ppg'] = None if donor['ppg'] is None else donor['ppg'].astype(np.float64).copy()
        out['abp'] = None if donor['abp'] is None else donor['abp'].astype(np.float64).copy()
    elif kind == 'roll':
        k_s = int(spec[1] * FS)
        for k in ('ppg', 'abp'):
            if out[k] is not None:
                out[k] = np.roll(out[k], k_s)
    else:
        raise ValueError(kind)
    if kind not in ('shift', 'swap'):
        for k in KEYS:
            if out[k] is not None:
                out[k] = _round(k, out[k])
    return out


def _as_list(x):
    # A channel the record has but whose samples are all missing stays a list of nulls (as in
    # training and as a monitor sending an empty channel); only a channel not sent at all is None.
    if x is None:
        return None
    return [None if not np.isfinite(v) else float(v) for v in x]


_DET = None


def brain_m2(row, code, tag):
    """One window through the brain's real EmergencyDetector (pinned trees, live-rule fallback)."""
    global _DET
    from sw_brain.detectors import EmergencyDetector
    from sw_brain.service import BedState
    if _DET is None:
        _DET = EmergencyDetector()
    _DET.reset()
    window = {'bed_id': tag, 'window_start': 0, 'monitor_alarms': [],
              **{k: _as_list(row[k]) for k in KEYS}}
    if window['ecg2'] is not None:
        window['ecg_leads'] = ['II', 'V']
    state = BedState(tag, last_alarm_code=code, alarm_until_ms=10 ** 12, prealarm_window=window)
    r = _DET.evaluate(window, state, 1)
    x = r['extra']
    if r['score'] is None:
        return 1.0, True, 'none'
    if x.get('path') == 'gbt_prealarm':
        return float(r['score']), bool(x['positive']), f"trees_{x['features']['ecg_leads_used']}lead"
    return float(r['score']), bool(x['positive']), 'live_rule'


_DATA = None


def _init(paths):
    global _DATA
    with np.load(paths[0]) as z:
        d = {k: z[k] for k in z.files}
    hold = np.load(paths[1])
    d = {k: v[hold] for k, v in d.items()}
    with np.load(paths[2]) as z:
        sh = {k: z[k] for k in z.files}
    assert np.array_equal(sh['event'], d['event']) and np.array_equal(sh['label'], d['label'])
    _DATA = (d, sh)


def _row(src, i, suffix=''):
    return {k: (src[k + suffix][i] if src['has_' + k + suffix][i] else None) for k in KEYS}


def run_condition(args):
    ci, name = args
    d, sh = _DATA
    spec = CONDITIONS[name][2]
    y = d['label'].astype(bool); codes = d['code'].astype(str)
    n = y.size
    has_ppg = np.flatnonzero(d['has_ppg'])
    false_ppg = np.flatnonzero(d['has_ppg'] & ~y)
    scores, preds, paths = np.zeros(n), np.zeros(n, bool), []
    for i in range(n):
        rng = np.random.default_rng([SEED, ci, i])
        ctx = {}
        if spec is not None and spec[0] == 'shift':
            tag = f'{spec[1]:g}'.replace('.', 'p')
            ctx['shift_row'] = _row(sh, i, f'_s{tag}')
        if spec is not None and spec[0] == 'swap':
            pool = has_ppg if spec[1] == 'any' else false_ppg
            pool = pool[pool != i]
            ctx['donor'] = _row(d, int(rng.choice(pool)))
        s, p, path = brain_m2(perturb(spec, _row(d, i), rng, ctx), codes[i], f'{name}:{i}')
        scores[i], preds[i] = s, p
        paths.append(path)
    return name, scores, preds, paths


def _block(y, s, p):
    m = summary(y, s, p)
    return {k: (None if isinstance(v, float) and v != v else (round(v, 4) if isinstance(v, float) else v)) for k, v in m.items()}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(windows, mask, shift, out, scores_npz=None, procs=None):
    t0 = time.time()
    _init((windows, mask, shift))
    d, sh = _DATA
    # Shift 0 rebuilt on the server must equal the training windows exactly.
    for k in KEYS:
        a, b = d[k], sh[f'{k}_s0']
        assert np.array_equal(d['has_' + k], sh[f'has_{k}_s0']), k
        assert np.array_equal(np.isnan(a), np.isnan(b)) and np.allclose(a[~np.isnan(a)], b[~np.isnan(b)], atol=0), k
    y = d['label'].astype(bool); codes = d['code'].astype(str); src = d['source'].astype(str)
    names = list(CONDITIONS)
    procs = procs or max(1, min(6, (os.cpu_count() or 2) - 1))
    with Pool(procs, initializer=_init, initargs=((windows, mask, shift),)) as pool:
        res = {name: (s, p, paths) for name, s, p, paths in pool.imap_unordered(run_condition, list(enumerate(names)))}
    s0, p0, _ = res['clean']
    # Clean run must reproduce the published held-out scores (train2: 2-lead if ecg2, else 1-lead).
    parity = None
    if scores_npz:
        with np.load(scores_npz) as z:
            hold = np.load(mask)
            live = np.where(z['has2'], z['s2'], z['s1'])[hold]
        parity = float(np.max(np.abs(live - s0)))
    results = {}
    for name in names:
        s, p, paths = res[name]
        fam, strength, _ = CONDITIONS[name]
        entry = {'family': fam, 'strength': strength, 'paths': {k: paths.count(k) for k in sorted(set(paths))}}
        for ds in ('cinc2015', 'vtac'):
            base = src == ds
            blk = {'ALL': _block(y[base], s[base], p[base])}
            if ds == 'cinc2015':
                for c in ALARM_TYPES:
                    m = base & (codes == c)
                    blk[c] = _block(y[m], s[m], p[m])
            # Flips against the clean run: true alarms newly called "likely false", and the reverse.
            blk['true_alarms_flipped_to_false'] = int(np.sum(base & y & p0 & ~p))
            blk['false_alarms_flipped_to_real'] = int(np.sum(base & ~y & ~p0 & p))
            blk['mean_abs_score_change'] = round(float(np.mean(np.abs(s[base] - s0[base]))), 4)
            entry[ds] = blk
        results[name] = entry
    report = {
        'what': 'M2 robustness + forged-input check on the locked held-out windows, brain code path (offline)',
        'seed': SEED, 'n': {'cinc2015': int((src == 'cinc2015').sum()), 'vtac': int((src == 'vtac').sum())},
        'inputs_sha256': {'windows_v13.npz': sha(windows), 'heldout_mask.npy': sha(mask), 'heldout_shift.npz': sha(shift)},
        'models': {'1lead': __import__('sw_brain.m2gbt', fromlist=['SHA256']).SHA256,
                   '2lead': __import__('sw_brain.m2gbt', fromlist=['SHA256_2']).SHA256_2},
        'clean_parity_vs_heldout_scores2_max_abs_diff': parity,
        'unavailable_rule': 'no advice -> alarm stands: counted as predicted real, score 1.0',
        'host': platform.node(), 'machine': platform.machine(), 'python': platform.python_version(),
        'numpy': np.__version__, 'elapsed_s': round(time.time() - t0, 1), 'conditions': results}
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(report, indent=1) + '\n')
    for name in names:
        r = results[name]
        print(f"{name:32s} " + '  '.join(
            f"{ds[:4]} sc {r[ds]['ALL']['score']:.3f} tpr {r[ds]['ALL']['TPR']:.3f} tnr {r[ds]['ALL']['TNR']:.3f} "
            f"auc {r[ds]['ALL']['AUROC']:.3f} flipT {r[ds]['true_alarms_flipped_to_false']}"
            for ds in ('cinc2015', 'vtac')) + f"  {r['paths']}")


if __name__ == '__main__':
    os.environ.setdefault('OMP_NUM_THREADS', '1')
    main(*sys.argv[1:6])
