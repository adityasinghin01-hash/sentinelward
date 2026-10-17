"""Build the training table on LinuxONE: the exact 10 s window the live brain sees.

Live path (simulator + brain): sw_data picks ECG lead II (else first ECG lead), PLETH and
ABP/ART, maps -32768 to NaN, converts uV to mV, resamples the whole record to 125 Hz
with gap-safe resample_poly; the simulator rounds ECG/PPG/ABP to 3/2/1 decimals and
raises the monitor alarm in the message of pack second 300. The brain's pre-alarm
window is pack seconds 290-299, i.e. samples [290*125, 300*125). This module repeats
exactly that with the same sw_data functions.

    python -m m2gbt.prep <cinc_training_dir> <vtac_prealarm.npz> <out_windows.npz>
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

FS = 125
ALARM_S = 300
ROUND = {'ecg': 3, 'ppg': 2, 'abp': 1}   # simulator/ward_script.yaml rounding


def _other_ecg(names, first):
    from sw_data.dsp import ECG_LEADS, _norm
    leads = {_norm(e) for e in ECG_LEADS}
    for i, n in enumerate(names):
        if i != first and (_norm(n) in leads or _norm(n).startswith('ECG')):
            return i
    return None


def _round(key, y):
    return None if y is None else np.round(y, ROUND['ecg' if key == 'ecg2' else key])


def cinc_windows(folder: Path):
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
        duration = int(rec.sig_len // fs)
        n = int(round(duration * fs))
        e1, _ = pick_ecg(names)
        picks = {'ecg': e1, 'ecg2': _other_ecg(names, e1) if e1 is not None else None,
                 'ppg': pick_channel(names, ['PLETH']), 'abp': pick_channel(names, ['ABP', 'ART'])}
        row = {'source': 'cinc2015', 'record': stem.name, 'event': stem.name, 'code': alarm['code'],
               'label': bool(alarm['true_alarm']), 'split': '', 'names': ','.join(names)}
        for key, idx in picks.items():
            if idx is None:
                row[key] = None
                continue
            x = clean_missing(rec.p_signal[:, idx])
            if key.startswith('ecg'):
                x, _, _ = ecg_to_mv(x, units[idx])
            y = window_resample(x, fs, 0, n)
            row[key] = _round(key, y[(ALARM_S - 10) * FS:ALARM_S * FS])
        rows.append(row)
    return rows


def vtac_windows(npz: Path):
    from sw_data.dsp import ecg_to_mv, pick_channel, pick_ecg, window_resample
    with np.load(npz) as z:
        d = {k: z[k] for k in z.files}     # decompress once, not per access
    fs = int(d['fs'])
    off = (ALARM_S - 10 - int(d['start_s'])) * fs     # 290 s inside the stored [288, 302) slice
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
        row = {'source': 'vtac', 'record': str(d['record'][i]), 'event': str(d['event'][i]), 'code': 'VTACH',
               'label': bool(d['label'][i]), 'split': str(d['split'][i]), 'names': ','.join(names)}
        for key, idx in picks.items():
            if idx is None or not np.isfinite(sig[idx]).any():
                row[key] = None
                continue
            x = sig[idx]
            if key.startswith('ecg'):
                x, _, _ = ecg_to_mv(x, units[idx])
            row[key] = _round(key, window_resample(x, fs, off, 10 * fs, margin_s=1.0))
        rows.append(row)
    return rows


def save(rows, out):
    arr = lambda key: np.stack([r[key] if r[key] is not None else np.full(10 * FS, np.nan) for r in rows]).astype('<f4')
    has = lambda key: np.array([r[key] is not None for r in rows])
    np.savez_compressed(out, **{k: arr(k) for k in ('ecg', 'ecg2', 'ppg', 'abp')},
                        **{f'has_{k}': has(k) for k in ('ecg', 'ecg2', 'ppg', 'abp')},
                        **{k: np.array([r[k] for r in rows]) for k in ('source', 'record', 'event', 'code', 'label', 'split', 'names')})


if __name__ == '__main__':
    cinc = cinc_windows(Path(sys.argv[1]))
    vtac = vtac_windows(Path(sys.argv[2]))
    print('cinc', len(cinc), 'vtac', len(vtac))
    save(cinc + vtac, sys.argv[3])
