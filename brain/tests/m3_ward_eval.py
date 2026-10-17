"""All-pack companion to tests_system/clean_ward_eval.py, with joined/online denominators.

Usage: python brain/tests/m3_ward_eval.py PACKS OUTPUT_PREFIX [seconds]
No attacks, injected drift, cuffs, or alarms, matching clean_ward_eval. The short
alarm records stop at source end. Counts exclude the first 30 s after admission.
The detailed JSONL preserves M3 evidence plus independently measured monitor HR.
"""
import collections
import json
from pathlib import Path
import sys
import numpy as np
from sw_brain.service import BrainService
from sw_brain.detectors import pulse_metrics


class Bus:
    def __init__(self):
        self.published = []
    def publish(self, *args, **kwargs):
        self.published.append(args)
    def subscribe(self, *args, **kwargs):
        pass


def val(x):
    return float(x) if np.isfinite(x) else None


def evaluate(packs, prefix, seconds=1200):
    summary = {}
    with open(str(prefix) + '.jsonl', 'w') as output:
        for path in sorted(Path(packs).glob('B*.npz')):
            bed = path.stem
            data = np.load(path)
            join = {'B04': 90, 'B07': 540}.get(bed, 0)
            duration = min(seconds - join, len(data['ecg']) // 125)
            bus = Bus()
            service = BrainService(bus)
            counts, blockers = collections.Counter(), collections.Counter()
            for sec in range(duration):
                sl = slice(sec * 125, (sec + 1) * 125)
                msg = dict(v=1, type='vitals', bed_id=bed, device_id='MON-' + bed[1:],
                           seq=sec+1, ts=(sec+join)*1000, fs=125,
                           ecg=[val(x) for x in data['ecg'][sl]], ppg=[val(x) for x in data['ppg'][sl]],
                           abp=[val(x) for x in data['abp'][sl]] if 'abp' in data.files else None,
                           hr=val(data['hr'][sec]), spo2=val(data['spo2'][sec]), rr=val(data['rr'][sec]),
                           nibp=None, monitor_alarm=None)
                service.receive(f'ward/bed/{bed}/vitals', json.dumps(msg), received_ms=msg['ts']+50)
                if (sec+join) % 5 != 4 or sec < 10:
                    continue
                bus.published.clear()
                verdict = service.tick((sec+join+1)*1000)[0]
                m3 = next(args[1] for args in bus.published if args[0].endswith('/score/M3'))
                # Independent peak rate distinguishes autocorrelation half-rate from missing peaks.
                window = service.beds[bed].windows[-1]
                ppg = pulse_metrics(window, 'ppg')
                peaks = ppg['peaks'] if ppg else []
                peak_rate = 7500/np.median(np.diff(peaks)) if len(peaks) >= 2 else None
                row = dict(bed=bed, source_s=sec+1, monitor_hr=val(np.nanmedian(data['hr'][max(0,sec-9):sec+1])),
                           ppg_peak_rate=peak_rate, verdict=verdict['verdict'], scores=verdict['scores'],
                           m3=m3, reasons=verdict['reasons'])
                output.write(json.dumps(row) + '\n')
                if sec >= 30:
                    counts[verdict['verdict']] += 1
                    if verdict['verdict'] != 'NORMAL':
                        for model, score in verdict['scores'].items():
                            if score is not None and score >= .5:
                                blockers[model] += 1
                            elif score is None and model in ('M1','M3','M4','M5'):
                                blockers[model+':null'] += 1
            summary[bed] = dict(join_s=join, online_s=duration, counts=dict(counts), blockers=dict(blockers),
                                normal_pct=round(100*counts['NORMAL']/max(1,sum(counts.values())),2))
            print(bed, summary[bed], flush=True)
    Path(str(prefix)+'.json').write_text(json.dumps(summary, indent=2)+'\n')


if __name__ == '__main__':
    evaluate(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv)>3 else 1200)
