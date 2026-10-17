"""Alarm-fatigue numbers for M2 at the LIVE thresholds, recomputed from the held-out JSON.

Reads ml_v2/results/heldout2.json (2-lead model M2-gbt2, the one the brain runs when the
second ECG lead is present) and ml_v2/results/heldout.json (1-lead model M2-gbt, the
brain's fallback). Both files hold confusion counts computed at the per-alarm-type
thresholds stored in the deployed artifacts; this script checks that those thresholds
match ml_v2/artifacts/*.json and prints, per held-out set and alarm type:

  false alarms marked likely-false  = TN / (TN + FP)   (TNR)
  true alarms missed (marked false) = FN / (TP + FN)   (1 - TPR)

Advice only: in SentinelWard the monitor alarm still sounds and nothing is suppressed;
M2 only labels the alarm. No model is run here, no number is invented.

Usage: python ml_v2/results/fatigue.py
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ART = HERE.parent / 'artifacts'

SETS = [('cinc2015', 'CinC 2015 held-out'), ('vtac', 'VTaC test')]
TYPES = ['ASYSTOLE', 'BRADY', 'TACHY', 'VFIB', 'VTACH']


def _load(name):
    return json.loads((HERE / name).read_text())


def _pct(a, b):
    return f'{100.0 * a / b:5.1f}%' if b else '   n/a'


def _line(label, c):
    neg = c['TN'] + c['FP']
    pos = c['TP'] + c['FN']
    return (f'  {label:<9} n={c["n"]:<4} false alarms marked likely-false {_pct(c["TN"], neg)} '
            f'({c["TN"]}/{neg})   true alarms missed {_pct(c["FN"], pos)} ({c["FN"]}/{pos})')


def _report(title, heldout, key):
    print(title)
    for ds, ds_label in SETS:
        print(f' {ds_label}')
        all_key = f'{ds}/ALL'
        if all_key in heldout and key in heldout[all_key]:
            print(_line('ALL', heldout[all_key][key]))
        for t in TYPES:
            k = f'{ds}/{t}'
            if k in heldout and key in heldout[k]:
                print(_line(t, heldout[k][key]))
    print()


def main():
    h2 = _load('heldout2.json')
    h1 = _load('heldout.json')
    art2 = json.loads((ART / 'm2_gbt2_2026-10-17.json').read_text())
    art1 = json.loads((ART / 'm2_gbt_2026-10-17.json').read_text())
    ok2 = art2['thresholds'] == h2['thresholds_2lead']
    ok1 = art1['thresholds'] == h1['thresholds']
    print('M2 alarm-fatigue numbers at the live thresholds (advice only: the monitor alarm still sounds)')
    print(f'2-lead {h2["model_version"]}: heldout2.json thresholds == deployed artifact: {ok2}')
    print(f'1-lead M2-gbt-2026-10-17: heldout.json thresholds == deployed artifact: {ok1}')
    print()
    _report('2-lead trees (live when the second ECG lead is present) - heldout2.json gbt_2lead',
            h2['heldout'], 'gbt_2lead')
    _report('1-lead trees (live fallback) - heldout.json gbt', h1['heldout'], 'gbt')
    if not (ok1 and ok2):
        raise SystemExit('threshold mismatch: numbers above are NOT at the live thresholds')


if __name__ == '__main__':
    main()
