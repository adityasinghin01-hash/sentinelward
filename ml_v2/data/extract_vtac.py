"""Stream the 10 s before every labelled VTaC alarm out of the zip (never unzips it whole).

Runs on the TEST LinuxONE server (numpy only). For each event in event_labels.csv it
reads annotated_waveforms/<record>/<event>.hea/.dat from the zip, decodes WFDB format 16
(little-endian int16, interleaved; raw -32768 = missing), and keeps all channels in
physical units at the native 250 Hz for [288 s, 302 s): the 10 s pre-alarm window
(290-300 s; the alarm onset is at 300 s, per the VTaC v1.1 PhysioNet page) plus 2 s of
filter context per side. Resampling to 125 Hz happens on the BUILD server with the same
sw_data code the live simulator uses.

Usage: python3 extract_vtac.py <vtac.zip> <out.npz>
"""
from __future__ import annotations

import csv
import io
import re
import sys
import zipfile

import numpy as np

FS = 250
ALARM_S = 300
START_S, STOP_S = 288, 302           # 10 s window + 2 s context each side
MAX_CH = 8


def parse_header(text: str):
    lines = [l for l in text.splitlines() if l.strip() and not l.startswith('#')]
    head = lines[0].split()
    n_sig, fs, n_samp = int(head[1]), float(head[2]), int(head[3])
    chans = []
    for line in lines[1:1 + n_sig]:
        parts = line.split()
        fmt = parts[1]
        m = re.match(r'([-+0-9.eE]+)(?:\(([-+0-9]+)\))?(?:/(\S+))?', parts[2])
        gain = float(m.group(1)) or 200.0
        baseline = int(m.group(2)) if m.group(2) is not None else (int(parts[4]) if len(parts) > 4 else 0)
        unit = m.group(3) or ''
        chans.append({'fmt': fmt, 'gain': gain, 'baseline': baseline, 'unit': unit,
                      'name': ' '.join(parts[8:]) if len(parts) > 8 else f'ch{len(chans)}'})
    return n_sig, fs, n_samp, chans


def decode(dat: bytes, n_sig: int, chans, a: int, b: int):
    if any(c['fmt'] != '16' for c in chans):
        raise ValueError('only WFDB format 16 supported')
    raw = np.frombuffer(dat, dtype='<i2')            # explicit little-endian on big-endian s390x
    raw = raw[: (raw.size // n_sig) * n_sig].reshape(-1, n_sig)[a:b].astype(np.float64)
    out = np.empty_like(raw)
    for j, c in enumerate(chans):
        col = raw[:, j]
        phys = (col - c['baseline']) / c['gain']
        phys[col == -32768] = np.nan
        out[:, j] = phys
    return out.T


def main(zpath: str, out: str):
    z = zipfile.ZipFile(zpath)
    root = z.namelist()[0].split('/')[0] + '/'
    labels = list(csv.DictReader(io.StringIO(z.read(root + 'event_labels.csv').decode())))
    split = {r['event']: r['split'] for r in csv.DictReader(io.StringIO(z.read(root + 'benchmark_data_split.csv').decode()))}
    votes = {}
    for r in csv.DictReader(io.StringIO(z.read(root + 'event_label_per_annotator.csv').decode())):
        if r['is_adjudication'].upper() != 'TRUE':
            votes.setdefault(r['event'], []).append(r['decision'].upper() == 'TRUE')
    a, b = START_S * FS, STOP_S * FS
    n = len(labels)
    sig = np.full((n, MAX_CH, b - a), np.nan, dtype='<f4')
    names = np.full((n, MAX_CH), '', dtype='<U12')
    units = np.full((n, MAX_CH), '', dtype='<U8')
    keep = np.zeros(n, bool); errors = []
    for i, r in enumerate(labels):
        stem = f"{root}annotated_waveforms/{r['record']}/{r['event']}"
        try:
            n_sig, fs, n_samp, chans = parse_header(z.read(stem + '.hea').decode())
            if fs != FS or n_samp < b:
                raise ValueError(f'fs {fs} or length {n_samp} unexpected')
            x = decode(z.read(stem + '.dat'), n_sig, chans, a, b)
            k = min(n_sig, MAX_CH)
            sig[i, :k] = x[:k]
            names[i, :k] = [c['name'] for c in chans[:k]]
            units[i, :k] = [c['unit'] for c in chans[:k]]
            keep[i] = True
        except Exception as exc:  # report, never silently drop
            errors.append(f"{r['event']}: {exc}")
        if i % 500 == 0:
            print(i, n, len(errors), flush=True)
    vote_frac = np.array([np.mean(votes[r['event']]) if r['event'] in votes else np.nan for r in labels])
    np.savez_compressed(out, signals=sig, names=names, units=units, ok=keep,
                        label=np.array([r['decision'].strip().upper() == 'TRUE' for r in labels]),
                        record=np.array([r['record'] for r in labels]),
                        event=np.array([r['event'] for r in labels]),
                        split=np.array([split.get(r['event'], '') for r in labels]),
                        vote_true_fraction=vote_frac,
                        fs=FS, start_s=START_S, alarm_s=ALARM_S)
    print('events', n, 'ok', int(keep.sum()), 'errors', len(errors))
    for e in errors[:20]:
        print('ERR', e)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
