#!/usr/bin/env python3
"""Recompute short-run tick summaries from unchanged scale originals."""
import json
import statistics
from pathlib import Path

root = Path(__file__).resolve().parent
print('beds ticks median_ms max_ms max_dropped_total max_invalid_in_total')
for beds in (12, 24, 48, 96):
    rows = [json.loads(line.split('tick_stats ', 1)[1])
            for line in (root / f'scale-{beds}-ticks.txt').read_text().splitlines()
            if 'tick_stats ' in line]
    rows = [r for r in rows if r['beds'] == beds and r['verdicts'] == beds]
    ticks = [r['tick_ms'] for r in rows]
    print(beds, len(rows), f'{statistics.median(ticks):.2f}', f'{max(ticks):.2f}',
          max(r['dropped_total'] for r in rows), max(r['invalid_in_total'] for r in rows))
