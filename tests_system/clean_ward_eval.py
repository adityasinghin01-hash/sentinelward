"""Clean-ward verdict mix: feed real bed packs (no attacks) through the full brain and count verdicts.
Usage: PYTHONPATH=brain:common python tests_system/clean_ward_eval.py <packs_dir> <seconds>
B03/B04/B07 (330 s alarm recordings) are judged separately by the ward-script tests.
"""
import sys, json, glob, collections, numpy as np
from sw_brain.service import BrainService
P = sys.argv[1]; SECONDS = int(sys.argv[2])
class Bus:
    def __init__(self): self.published = []
    def publish(self, *a, **k): self.published.append(a)
    def subscribe(self, *a, **k): pass
def val(x): return None if not np.isfinite(x) else float(x)
counts = collections.defaultdict(collections.Counter)
blockers = collections.defaultdict(collections.Counter)
for f in sorted(glob.glob(P + '/B*.npz')):
    bed = f.split('/')[-1][:3]
    if bed in ('B03', 'B04', 'B07'): continue  # 330 s alarm recordings, judged separately
    d = np.load(f); svc = BrainService(Bus()); n = int(bed[1:])
    for sec in range(SECONDS):
        sl = slice(sec * 125, sec * 125 + 125)
        msg = {'v': 1, 'type': 'vitals', 'bed_id': bed, 'device_id': f'MON-{n:02d}', 'seq': sec + 1,
               'ts': sec * 1000, 'fs': 125, 'ecg': [val(x) for x in d['ecg'][sl]], 'ppg': [val(x) for x in d['ppg'][sl]],
               'abp': [val(x) for x in d['abp'][sl]] if 'abp' in d.files else None,
               'hr': val(d['hr'][sec]), 'spo2': val(d['spo2'][sec]), 'rr': val(d['rr'][sec]),
               'nibp': None, 'monitor_alarm': None}
        svc.receive(f'ward/bed/{bed}/vitals', json.dumps(msg), received_ms=sec * 1000 + 50)
        if sec % 5 == 4 and sec >= 10:
            for v in svc.tick((sec + 1) * 1000):
                counts[bed][v['verdict']] += 1
                if v['verdict'] == 'UNSURE':
                    for m, sc in v['scores'].items():
                        if sc is None: blockers[bed][m + ':null'] += 1
                        elif sc >= .5: blockers[bed][m + ':high'] += 1
tot = collections.Counter()
for bed, c in counts.items():
    tot += c; print(bed, dict(c), '| blockers:', dict(blockers[bed].most_common(3)))
print('ALL', dict(tot), f"NORMAL {100*tot['NORMAL']/sum(tot.values()):.0f}%")
