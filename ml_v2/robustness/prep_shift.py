"""Rebuild the held-out pre-alarm windows with the window moved earlier by s seconds.

Time-shift perturbation for ml_v2/robustness/run.py. Same steps as m2gbt.prep (same sw_data
functions, same lead picks, same rounding), but the 10 s window is record seconds
[290 - s, 300 - s) instead of [290, 300): the alarm timestamp is late by s seconds, so the
model sees s seconds less of the run-up to the alarm. Shift 0 must reproduce m2gbt.prep
exactly (run.py asserts this against windows_v13.npz).

Runs on the BUILD LinuxONE, where the recordings are (read-only):

    python -m robustness.prep_shift <cinc_training_dir> <vtac_prealarm.npz> <heldout_mask.npy> <out.npz>
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from m2gbt.prep import FS, ALARM_S, _other_ecg, _round

SHIFTS = (0.0, 0.5, 1.0, 2.0)
KEYS = ('ecg', 'ecg2', 'ppg', 'abp')


def cinc_rows(folder: Path):
    import wfdb
    from sw_data.cinc2015 import parse_alarm
    from sw_data.dsp import clean_missing, ecg_to_mv, pick_channel, pick_ecg, window_resample
    rows = []
    for stem in sorted(p.with_suffix('') for p in folder.glob('*.hea')):
        rec = wfdb.rdrecord(str(stem))
        alarm = parse_alarm(rec.comments or [])
        fs = float(rec.fs)
        names = [str(n) for n in rec.sig_name]
        units = [str(u) for u in rec.units]
        n = int(round(int(rec.sig_len // fs) * fs))
        e1, _ = pick_ecg(names)
        picks = {'ecg': e1, 'ecg2': _other_ecg(names, e1) if e1 is not None else None,
                 'ppg': pick_channel(names, ['PLETH']), 'abp': pick_channel(names, ['ABP', 'ART'])}
        row = {'record': stem.name, 'event': stem.name, 'code': alarm['code'], 'label': bool(alarm['true_alarm'])}
        for key, idx in picks.items():
            if idx is None:
                row.update({(key, s): None for s in SHIFTS})
                continue
            x = clean_missing(rec.p_signal[:, idx])
            if key.startswith('ecg'):
                x, _, _ = ecg_to_mv(x, units[idx])
            y = window_resample(x, fs, 0, n)
            for s in SHIFTS:
                a = int(round((ALARM_S - 10 - s) * FS))
                row[(key, s)] = _round(key, y[a:a + 10 * FS])
        rows.append(row)
    return rows


def vtac_rows(npz: Path):
    from sw_data.dsp import ecg_to_mv, pick_channel, pick_ecg, window_resample
    with np.load(npz) as z:
        d = {k: z[k] for k in z.files}
    fs = int(d['fs'])
    rows = []
    for i in range(d['label'].size):
        if not d['ok'][i]:
            continue
        names = [str(n) for n in d['names'][i] if str(n)]
        units = [str(u) for u in d['units'][i][:len(names)]]
        sig = d['signals'][i].astype(np.float64)
        e1, _ = pick_ecg(names)
        picks = {'ecg': e1, 'ecg2': _other_ecg(names, e1) if e1 is not None else None,
                 'ppg': pick_channel(names, ['PLETH']), 'abp': pick_channel(names, ['ABP', 'ART'])}
        row = {'record': str(d['record'][i]), 'event': str(d['event'][i]), 'code': 'VTACH', 'label': bool(d['label'][i])}
        for key, idx in picks.items():
            if idx is None or not np.isfinite(sig[idx]).any():
                row.update({(key, s): None for s in SHIFTS})
                continue
            x = sig[idx]
            if key.startswith('ecg'):
                x, _, _ = ecg_to_mv(x, units[idx])
            for s in SHIFTS:
                off = int(round((ALARM_S - 10 - s - int(d['start_s'])) * fs))
                row[(key, s)] = _round(key, window_resample(x, fs, off, 10 * fs, margin_s=1.0))
        rows.append(row)
    return rows


def main(cinc_dir, vtac_npz, mask_path, out):
    rows = cinc_rows(Path(cinc_dir)) + vtac_rows(Path(vtac_npz))
    hold = np.load(mask_path)
    assert hold.size == len(rows), (hold.size, len(rows))
    rows = [r for r, h in zip(rows, hold) if h]
    blank = np.full(10 * FS, np.nan)
    arrays = {}
    for s in SHIFTS:
        tag = f'{s:g}'.replace('.', 'p')
        for k in KEYS:
            arrays[f'{k}_s{tag}'] = np.stack([r[(k, s)] if r[(k, s)] is not None else blank for r in rows]).astype('<f4')
            arrays[f'has_{k}_s{tag}'] = np.array([r[(k, s)] is not None for r in rows])
    np.savez_compressed(out, shifts=np.array(SHIFTS), record=np.array([r['record'] for r in rows]),
                        event=np.array([r['event'] for r in rows]), code=np.array([r['code'] for r in rows]),
                        label=np.array([r['label'] for r in rows]), **arrays)
    print('held-out rows', len(rows), 'shifts', SHIFTS)


if __name__ == '__main__':
    main(*sys.argv[1:5])
