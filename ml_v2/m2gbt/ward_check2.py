"""Ward chain check (doc 00 v1.3): real bed packs -> sw_sim WardRun -> BrainService, no hub.

Plays the 20-minute ward script from a pack folder on an instant clock, hands every vitals
message (as JSON, like the hub would) to BrainService, ticks every 5 s and reports, for each
monitor alarm, the M2 score envelope (model_version, score, threshold) and the verdict.

    python -m m2gbt.ward_check2 <packs_dir> <ward_script.yaml> <out.json>
"""
from __future__ import annotations

import json
import sys
import tempfile
import time


class _Collect:
    def __init__(self):
        self.messages = []

    def connect(self):
        pass

    def publish(self, message):
        self.messages.append(message)
        return True

    def subscribe(self, *a, **k):
        pass

    def close(self):
        pass


def main(packs_dir, script_path, out_path):
    import sw_common
    from sw_brain.io import MemoryBus
    from sw_brain.service import BrainService
    from sw_sim.clock import InstantClock
    from sw_sim.config import load_script
    from sw_sim.engine import WardRun
    from sw_sim.packs import load_packs
    script = load_script(script_path)
    packs = load_packs(packs_dir, [b.pack_name for b in script.beds])
    bus = _Collect()
    with tempfile.TemporaryDirectory() as runs:
        WardRun(script, packs, run_id='lead2_chain', runs_dir=runs, clock=InstantClock(), bus=bus).run()
    msgs = sorted((m for m in bus.messages if m.get('type') == 'vitals'), key=lambda m: m['ts'])
    invalid = sum(bool(sw_common.validate(m)) for m in msgs)
    with_ecg2 = {}
    for m in msgs:
        if 'ecg2' in m:
            with_ecg2.setdefault(m['bed_id'], m['ecg_leads'])
    service = BrainService(MemoryBus())
    alarms = [(m['bed_id'], m['ts'], m['monitor_alarm']['code']) for m in msgs if m['monitor_alarm']]
    t0 = msgs[0]['ts']
    next_tick = (t0 // 5000 + 1) * 5000
    m2_by_alarm, tick_ms = {}, []
    for m in msgs + [None]:
        while m is None or m['ts'] >= next_tick:
            t = time.perf_counter()
            verdicts = {v['bed_id']: v for v in service.tick(next_tick)}
            tick_ms.append((time.perf_counter() - t) * 1000)
            for top, env, *_ in service.bus.published[-200:]:
                if top.endswith('/score/M2') and env['score'] is not None and env['extra'].get('path') == 'gbt_prealarm':
                    for bed, ts, code in alarms:
                        if env['bed_id'] == bed and env['extra'].get('features', {}).get('source_window_start') == ts - 10000:
                            m2_by_alarm.setdefault((bed, ts), {
                                'bed_id': bed, 'alarm': code, 't_s': (ts - t0) // 1000, 'model_version': env['model_version'],
                                'score': round(env['score'], 4), 'threshold': round(env['extra']['threshold'], 4),
                                'ecg_leads_used': env['extra']['features'].get('ecg_leads_used'),
                                'ecg_lead_names': env['extra']['features'].get('ecg_lead_names'),
                                'verdict': verdicts.get(bed, {}).get('verdict')})
            service.bus.published.clear()
            next_tick += 5000
            if m is None:
                break
        if m is None:
            break
        service.receive(f"ward/bed/{m['bed_id']}/vitals", json.dumps(m), received_ms=m['ts'])
    res = {'vitals_messages': len(msgs), 'invalid': invalid, 'beds_sending_ecg2': with_ecg2,
           'alarms': list(m2_by_alarm.values()), 'n_alarms_in_run': len(alarms),
           'median_tick_ms_12_beds': sorted(tick_ms)[len(tick_ms) // 2], 'max_tick_ms': max(tick_ms),
           'invalid_incoming': service.invalid_incoming}
    json.dump(res, open(out_path, 'w'), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == '__main__':
    main(*sys.argv[1:4])
