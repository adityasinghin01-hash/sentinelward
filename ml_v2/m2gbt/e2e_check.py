"""End-to-end parity on LinuxONE: replay held-out 2015 records through the live brain.

For each held-out CinC record that continues past the alarm (330 s 'l' records), build
the bed source with sw_data exactly as the ward does, send seconds 290-304 as v1 vitals
frames (simulator rounding, alarm in the frame of second 300) into BrainService, and
compare the published M2 score with the training-table score for that record.

    python -m m2gbt.e2e_check <cinc_dir> <out_dir_of_train>
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np


def main(cinc_dir, out_dir):
    from sw_brain.io import MemoryBus
    from sw_brain.service import BrainService
    import sw_brain
    from sw_data.beds import BedSpec, Paths
    from sw_data.cinc2015 import build_source
    out = Path(out_dir)
    with np.load(out / 'heldout_scores.npz') as z:
        d = {k: z[k] for k in z.files}
    rows = [i for i in np.flatnonzero(d['hold']) if d['src'][i] == 'cinc2015' and d['groups'][i].endswith('l')]
    diffs, times, report = [], [], []
    for i in rows:
        rec = d['groups'][i].split(':', 1)[1]
        src = build_source(BedSpec(bed_id='B01', device_id='MON-01', dataset='cinc2015', signals=['ecg'], record=rec),
                           Paths(cinc2015=Path(cinc_dir)))
        alarm = src.alarms[0]
        service = BrainService(MemoryBus())
        for sec in range(290, 305):
            wave = {k: (None if k not in src.waves else [None if not np.isfinite(v) else float(round(v, r))
                        for v in src.waves[k][sec * 125:(sec + 1) * 125]]) for k, r in (('ecg', 3), ('ppg', 2), ('abp', 1))}
            frame = {'v': 1, 'type': 'vitals', 'bed_id': 'B01', 'device_id': 'MON-01', 'seq': sec, 'ts': sec * 1000, 'fs': 125,
                     **wave, 'hr': None, 'spo2': None, 'rr': None, 'nibp': None,
                     'monitor_alarm': {'code': alarm['code'], 'priority': alarm['priority']} if sec == 300 else None}
            service.receive('ward/bed/B01/vitals', json.dumps(frame), received_ms=sec * 1000)
        t = time.perf_counter()
        verdict = service.tick(305000)[0]
        times.append((time.perf_counter() - t) * 1000)
        m2 = [m for top, m, *_ in service.bus.published if top.endswith('/score/M2')][-1]
        diffs.append(abs(m2['score'] - float(d['s'][i])))
        report.append({'record': rec, 'code': alarm['code'], 'label': bool(alarm['true_alarm']), 'brain_m2': m2['score'],
                       'train_table': float(d['s'][i]), 'model_version': m2['model_version'], 'path': m2['extra'].get('path'),
                       'verdict': verdict['verdict']})
    res = {'sw_brain_file': sw_brain.__file__, 'n_records': len(rows), 'max_abs_diff': float(max(diffs)),
           'median_tick_ms': float(np.median(times)), 'max_tick_ms': float(max(times)),
           'all_gbt_path': all(r['path'] == 'gbt_prealarm' for r in report),
           'all_emergency': all(r['verdict'] in ('EMERGENCY', 'BOTH') for r in report), 'records': report}
    json.dump(res, open(out / 'e2e_check.json', 'w'), indent=1)
    print(json.dumps({k: v for k, v in res.items() if k != 'records'}))


if __name__ == '__main__':
    main(*sys.argv[1:3])
