"""Replay the 20-minute ward through the chip service (no hub) and time the CNN per alarm.

Bed packs -> sw_sim WardRun (instant clock) -> vitals JSON -> ChipService (and, with
--brain, BrainService alongside, to check the chip scores exactly the windows the brain's M2
scores). Each alarm window is then re-scored --repeat times to give stable latency figures.

    python -m sw_chip.bench <packs_dir> <ward_script.yaml> <out.json> [--device nnpa|cpu] [--brain] [--repeat 20]
"""
from __future__ import annotations

import argparse
import json
import platform
import statistics
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


def ward_messages(packs_dir, script_path, beds=None):
    from sw_sim.clock import InstantClock
    from sw_sim.config import load_script
    from sw_sim.engine import WardRun
    from sw_sim.packs import load_packs
    script = load_script(script_path)
    packs = load_packs(packs_dir, [b.pack_name for b in script.beds])
    bus = _Collect()
    with tempfile.TemporaryDirectory() as runs:
        WardRun(script, packs, run_id='chip_bench', runs_dir=runs, clock=InstantClock(), bus=bus).run()
    msgs = sorted((m for m in bus.messages if m.get('type') == 'vitals'), key=lambda m: m['ts'])
    return [m for m in msgs if beds is None or m['bed_id'] in beds]


def pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    k = max(0, min(len(xs) - 1, int(round(q / 100 * len(xs) + 0.5)) - 1))
    return xs[k]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('packs'); ap.add_argument('script'); ap.add_argument('out')
    ap.add_argument('--device', default=None); ap.add_argument('--brain', action='store_true')
    ap.add_argument('--repeat', type=int, default=20)
    a = ap.parse_args(argv)
    import torch
    torch.set_num_threads(1)
    from .model import ChipModel
    from .service import ChipService
    model = ChipModel(device=a.device)
    published = []
    svc = ChipService(model, lambda t, p: published.append((t, json.loads(p))) or True)
    msgs = ward_messages(a.packs, a.script)
    brain = None
    if a.brain:
        from sw_brain.io import MemoryBus
        from sw_brain.service import BrainService
        brain = BrainService(MemoryBus())
    windows, brain_m2 = [], set()
    t0 = msgs[0]['ts']; next_tick = (t0 // 5000 + 1) * 5000
    for m in msgs + [None]:
        while brain is not None and (m is None or m['ts'] >= next_tick):
            brain.tick(next_tick)
            for top, env, *_ in brain.bus.published:
                if top.endswith('/score/M2') and env['extra'].get('path') == 'gbt_prealarm':
                    brain_m2.add((env['bed_id'], env['extra']['features']['source_window_start']))
            brain.bus.published.clear()
            next_tick += 5000
            if m is None:
                break
        if m is None:
            break
        payload = json.dumps(m)
        topic = f"ward/bed/{m['bed_id']}/vitals"
        job = svc.on_vitals(topic, payload, now_ms=m['ts'])
        if brain is not None:
            brain.receive(topic, payload, received_ms=m['ts'])
        if job is not None:
            windows.append((m['bed_id'],) + job)
    for _ in range(3):                      # warm-up (first device call)
        model.predict(windows[0][3], windows[0][1])
    live = svc.drain()
    lat_first = [x['latency_ms'] for x in live]
    lat = []
    for bed, code, ts, w in windows:
        for _ in range(a.repeat):
            lat.append(model.predict(w, code)[1])
    chip_keys = {(bed, ts - 10000) for bed, code, ts, w in windows}
    res = {'device': model.device, 'model': model.meta['model'], 'sha256': model.sha256,
           'host': platform.node(), 'machine': platform.machine(), 'torch': torch.__version__,
           'vitals': len(msgs), 'alarm_windows': len(windows),
           'latency_live_ms': {'n': len(lat_first), 'median': statistics.median(lat_first), 'p95': pct(lat_first, 95)},
           'latency_repeat_ms': {'n': len(lat), 'median': statistics.median(lat), 'p95': pct(lat, 95), 'repeat': a.repeat},
           'messages': [x for _, x in published]}
    if brain is not None:
        res['brain_m2_windows'] = len(brain_m2)
        res['chip_equals_brain_windows'] = chip_keys == brain_m2
        res['only_brain'] = sorted(brain_m2 - chip_keys); res['only_chip'] = sorted(chip_keys - brain_m2)
    json.dump(res, open(a.out, 'w'), indent=1)
    print(json.dumps({k: v for k, v in res.items() if k != 'messages'}))
    for x in res['messages']:
        print(json.dumps(x))


if __name__ == '__main__':
    main()
