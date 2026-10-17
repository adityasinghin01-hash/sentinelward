"""Held-out numbers through the live brain path (doc 00 v1.3, 2 ECG leads), on LinuxONE.

Part A, the ward path: every held-out 2015 record that continues past the alarm (330 s 'l'
records) is built with sw_data exactly as a bed pack (lead II + ecg2 by pick_ecg2, PLETH, ABP),
sent as vitals frames for seconds 290-304 (simulator rounding, ecg2 + ecg_leads when the record
has a second lead, alarm in the frame of second 300) into BrainService. The published M2 score is
compared with the train2 table score of the model the brain should pick.

Part B, every held-out event (188 CinC + 482 VTaC): the pre-alarm window of the training table is
sent as frames 290-299 (ecg2 only when the row has one) plus an alarm frame at 300, and the
held-out table is recomputed from the published M2 scores and the brain's own positive flag.

    python -m m2gbt.e2e_check2 <cinc_dir> <windows_v13.npz> <out_v13>
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

from . import ALARM_TYPES
from .metrics import summary

ROUND = {'ecg': 3, 'ecg2': 3, 'ppg': 2, 'abp': 1}


def _sec(arr, sec, r):
    return [None if not np.isfinite(v) else float(round(float(v), r)) for v in arr[sec * 125:(sec + 1) * 125]]


def _frame(sec, waves, alarm=None, leads=None):
    f = {'v': 1, 'type': 'vitals', 'bed_id': 'B01', 'device_id': 'MON-01', 'seq': sec, 'ts': sec * 1000, 'fs': 125,
         'ecg': waves.get('ecg'), 'ppg': waves.get('ppg'), 'abp': waves.get('abp'),
         'hr': None, 'spo2': None, 'rr': None, 'nibp': None, 'monitor_alarm': alarm}
    if waves.get('ecg2') is not None:
        f['ecg2'] = waves['ecg2']; f['ecg_leads'] = leads or ['ECG', 'ECG2']
    return f


def _run(frames):
    from sw_brain.io import MemoryBus
    from sw_brain.service import BrainService
    service = BrainService(MemoryBus())
    for f in frames:
        service.receive('ward/bed/B01/vitals', json.dumps(f), received_ms=f['ts'])
    t = time.perf_counter()
    verdict = service.tick(305000)[0]
    ms = (time.perf_counter() - t) * 1000
    m2 = [m for top, m, *_ in service.bus.published if top.endswith('/score/M2')][-1]
    return m2, verdict, ms


def main(cinc_dir, windows, out_dir):
    import sw_brain
    from sw_data.beds import BedSpec, Paths
    from sw_data.cinc2015 import build_source
    out = Path(out_dir)
    with np.load(out / 'heldout_scores2.npz') as z:
        d = {k: z[k] for k in z.files}
    with np.load(windows) as z:
        w = {k: z[k] for k in z.files}
    expect = np.where(d['has2'], d['s2'], d['s1'])

    # ---- Part A: ward path from the source records
    rows = [i for i in np.flatnonzero(d['hold']) if d['src'][i] == 'cinc2015' and d['groups'][i].endswith('l')]
    a_rep, a_diff, a_ms = [], [], []
    for i in rows:
        rec = d['groups'][i].split(':', 1)[1]
        src = build_source(BedSpec(bed_id='B01', device_id='MON-01', dataset='cinc2015', signals=['ecg'], record=rec),
                           Paths(cinc2015=Path(cinc_dir)))
        alarm = src.alarms[0]
        ch = src.source['channels']
        leads = [ch['ecg']['name']] + ([ch['ecg2']['name']] if 'ecg2' in ch else [])
        frames = []
        for sec in range(290, 305):
            waves = {k: (_sec(src.waves[k], sec, r) if k in src.waves else None) for k, r in ROUND.items()}
            frames.append(_frame(sec, waves, {'code': alarm['code'], 'priority': alarm['priority']} if sec == 300 else None, leads))
        m2, verdict, ms = _run(frames)
        a_ms.append(ms); a_diff.append(abs(m2['score'] - float(expect[i])))
        a_rep.append({'record': rec, 'code': alarm['code'], 'label': bool(alarm['true_alarm']), 'has_ecg2': 'ecg2' in src.waves,
                      'table_has_ecg2': bool(d['has2'][i]), 'leads': leads, 'brain_m2': m2['score'], 'expected': float(expect[i]),
                      'model_version': m2['model_version'], 'path': m2['extra'].get('path'), 'verdict': verdict['verdict']})

    # ---- Part B: every held-out event from the training-table window
    hold = np.flatnonzero(d['hold'])
    b_score, b_pos, b_diff, b_ms, b_versions, b_verdicts, b_rep = [], [], [], [], {}, {}, []
    for i in hold:
        frames = []
        for k, sec in enumerate(range(290, 300)):
            waves = {key: (_sec(w[key][i], k, ROUND[key]) if w['has_' + key][i] else None) for key in ROUND}
            frames.append(_frame(sec, waves))
        frames.append(_frame(300, {}, {'code': str(d['codes'][i]), 'priority': 'high'}))
        m2, verdict, ms = _run(frames)
        sc = np.nan if m2['score'] is None else float(m2['score'])
        b_ms.append(ms); b_score.append(sc); b_pos.append(bool(m2['extra'].get('positive')))
        b_diff.append(abs(sc - float(expect[i])) if m2['extra'].get('path') == 'gbt_prealarm' else np.nan)
        b_versions[m2['model_version']] = b_versions.get(m2['model_version'], 0) + 1
        b_verdicts[verdict['verdict']] = b_verdicts.get(verdict['verdict'], 0) + 1
        b_rep.append({'event': str(d['groups'][i]), 'code': str(d['codes'][i]), 'label': bool(d['y'][i]),
                      'brain_m2': sc, 'expected': float(expect[i]), 'model_version': m2['model_version'],
                      'brain_positive': bool(m2['extra'].get('positive')),
                      'table_positive': bool(d['pred2'][i] if d['has2'][i] else d['pred1'][i]),
                      'threshold': m2['extra'].get('threshold')})
    b_score = np.array(b_score); b_pos = np.array(b_pos); b_diff = np.array(b_diff)
    y, codes, src = d['y'][hold], d['codes'][hold], d['src'][hold]
    table = {}
    for name in ('cinc2015', 'vtac'):
        for c in ALARM_TYPES + ('ALL',):
            m = (src == name) & ((codes == c) if c != 'ALL' else True)
            if m.sum():
                table[f'{name}/{c}'] = summary(y[m], b_score[m], b_pos[m])
    flips = int(sum(bool(p) != bool(q) for p, q in zip(b_pos, np.where(d['has2'], d['pred2'], d['pred1'])[hold])))
    res = {'sw_brain_file': sw_brain.__file__,
           'A_ward_path': {'n_records': len(rows), 'with_ecg2': int(sum(r['has_ecg2'] for r in a_rep)),
                           'ecg2_presence_matches_table': all(r['has_ecg2'] == r['table_has_ecg2'] for r in a_rep),
                           'max_abs_diff': float(max(a_diff)), 'median_tick_ms': float(np.median(a_ms)),
                           'max_tick_ms': float(max(a_ms)),
                           'model_versions': sorted({r['model_version'] for r in a_rep}),
                           'all_gbt_path': all(r['path'] == 'gbt_prealarm' for r in a_rep),
                           'all_emergency': all(r['verdict'] in ('EMERGENCY', 'BOTH') for r in a_rep)},
           'B_heldout': {'n_events': int(hold.size), 'n_not_gbt_path': int(np.isnan(b_diff).sum()),
                         'max_abs_diff': float(np.nanmax(b_diff)), 'decision_flips': flips,
                         'model_versions': b_versions, 'verdicts': b_verdicts,
                         'median_tick_ms': float(np.median(b_ms)), 'table': table},
           'records_A': a_rep, 'records_B': b_rep}
    json.dump(res, open(out / 'e2e_check2.json', 'w'), indent=1)
    print(json.dumps({k: v for k, v in res.items() if not k.startswith('records')}, indent=1))


if __name__ == '__main__':
    main(*sys.argv[1:4])
