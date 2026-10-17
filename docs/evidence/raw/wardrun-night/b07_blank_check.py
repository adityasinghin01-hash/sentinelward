#!/usr/bin/env python3
"""Check B07 API continuity, not screen continuity; stdlib only.

Default: read bundled B07 ward-poll extracts. --source-root PATH reads original
PATH/wardrun{N,F1,F2,F3}/run{N,F1,F2,F3}.jsonl instead. T0 constants match
those runs' timeline2.py; only successful ward polls at T+0..1200 s count.
The legacy expression is copied verbatim in logic from metrics2.py.
"""
import argparse
import json
from pathlib import Path

T0 = {'N': 1792264341000, 'F1': 1792253431000,
      'F2': 1792254749000, 'F3': 1792256233000}
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source-root', type=Path)
args = parser.parse_args()
root = Path(__file__).resolve().parent
print('run polls legacy_count legacy_before_first legacy_after_first first_values_s empty_after_first legacy_range_s')
for run, start in T0.items():
    path = (args.source_root / f'wardrun{run}' / f'run{run}.jsonl'
            if args.source_root else root / f'b07-polls-{run}.jsonl')
    samples = []
    with path.open() as stream:
        for line in stream:
            r = json.loads(line)
            t = (r['wall_ms'] - start) / 1000
            if r.get('kind') != 'ward' or r.get('status') != 200 or not 0 <= t <= 1200:
                continue
            b = next((b for b in r.get('beds', []) if b['bed_id'] == 'B07'), None)
            if b is not None:
                samples.append((t, b))
    samples.sort(key=lambda s: s[0])
    def has_values(b):
        v = b.get('vitals')
        return isinstance(v, dict) and any(x is not None for x in v.values())
    first = next(t for t, b in samples if has_values(b))
    legacy = [t for t, b in samples if
              (b['display'] == 'empty' and t > 100) or
              (b.get('vitals') is None and b['display'] != 'empty')]
    before = sum(t < first for t in legacy)
    after = sum(t >= first for t in legacy)
    empty_after = sum(not has_values(b) for t, b in samples if t >= first)
    print(run, len(samples), len(legacy), before, after, f'{first:.3f}', empty_after,
          f'{min(legacy):.3f}..{max(legacy):.3f}' if legacy else 'none')
print('B07 joins at 540 s in simulator/ward_script.yaml. Legacy time > 100 is not prior receipt.')
print('These are saved API polls; rendered-screen continuity was not measured.')
