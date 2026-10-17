"""Batched bench (optional, bench only): does the z17 NNPA help when many windows are scored at once?

The live service (sw_chip.service) is unchanged: it still scores one alarm window at a time.
This bench times the same pinned CNN (ChipModel: same weights, same cnn_nnpa.tensors scaling)
on batches of real windows, nnpa:0 vs cpu, with torch threads = 1 and = all cores.

  run    one device per process:
         micro  - batch sizes 1,4,12,32,96,256 of real held-out windows; per batch:
                  input scaling + host->device + forward + sigmoid + device->host;
                  --warmup untimed + --iters timed calls; median, p95, windows/s.
         parity - all held-out windows scored in chunks of each batch size (scores saved).
         ward   - whole-ward pattern: --ward-beds beds' current 10 s windows (cut from the real
                  packs-v13 recordings, 12 packs x 8 offsets, advancing 5 s per tick) scored in ONE
                  batch every 5 s of wall time for --ward-ticks ticks; latency and process CPU.
  merge  cpu + nnpa runs -> one JSON, with max |nnpa - cpu| per batch size on the same windows.

    python -m sw_chip.batch_bench run --device nnpa --windows W.npz --mask M.npy --packs P --out nnpa.json
    python -m sw_chip.batch_bench run --device cpu  ... --out cpu.json
    python -m sw_chip.batch_bench merge cpu.json nnpa.json out.json [--ref training_scores.npy]
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import time
from pathlib import Path

import numpy as np

from .bench import pct

BATCHES = (1, 4, 12, 32, 96, 256)
KEYS = ('ecg', 'ppg', 'abp')
WIN = 1250          # 10 s at 125 Hz
STEP = 625          # 5 s tick at 125 Hz


def take(d, idx, codes):
    """Batch dict in the layout cnn_nnpa.tensors expects."""
    b = {k: d[k][idx] for k in KEYS}
    b.update({'has_' + k: d['has_' + k][idx] for k in KEYS})
    b['code'] = codes[idx]
    return b


def score(model, b):
    """(p[n], scale_ms, device_ms): the live predict() path, batched."""
    torch = model.torch
    t0 = time.perf_counter()
    x, a = model.mod.tensors(b)
    x, a = x.float(), a.float()
    t1 = time.perf_counter()
    with torch.no_grad():
        p = torch.sigmoid(model.net(x.to(model.device_kind), a.to(model.device_kind))).to('cpu')
    p = p.numpy().astype(np.float64).reshape(-1)
    t2 = time.perf_counter()
    return p, (t1 - t0) * 1000, (t2 - t1) * 1000


def stats(xs):
    return {'median': statistics.median(xs), 'p95': pct(xs, 95), 'max': max(xs)}


def micro(model, d, hi, codes, batches, warmup, iters):
    rows = []
    for bsz in batches:
        # 8 distinct batches of real held-out windows, cycled (wraps round the held-out set)
        sets = [take(d, hi[np.arange(j * bsz, (j + 1) * bsz) % hi.size], codes) for j in range(8)]
        for i in range(warmup):
            score(model, sets[i % 8])
        tot, dev, scl = [], [], []
        c0 = time.process_time(); w0 = time.perf_counter()
        for i in range(iters):
            _, s, dv = score(model, sets[i % 8])
            tot.append(s + dv); dev.append(dv); scl.append(s)
        cpu_s, wall_s = time.process_time() - c0, time.perf_counter() - w0
        med = statistics.median(tot)
        rows.append({'batch': bsz, 'iters': iters, 'warmup': warmup,
                     'total_ms': stats(tot), 'scaling_ms': stats(scl), 'device_ms': stats(dev),
                     'windows_per_s': bsz / (med / 1000), 'ms_per_window': med / bsz,
                     'process_cpu_per_wall': cpu_s / wall_s})
        print(json.dumps({'batch': bsz, 'median_ms': round(med, 3), 'p95_ms': round(pct(tot, 95), 3),
                          'windows_per_s': round(bsz / (med / 1000), 1)}), flush=True)
    return rows


def parity_scores(model, d, hi, codes, batches):
    out = {}
    for bsz in batches:
        ps = []
        for s in range(0, hi.size, bsz):
            ps.append(score(model, take(d, hi[s:s + bsz], codes))[0])
        out[str(bsz)] = np.concatenate(ps)
    return out


def ward_windows(packs_dir, beds, ticks):
    """Per tick, beds x 1250 current windows from the real ward packs (12 packs x offsets)."""
    names = sorted(p.stem for p in Path(packs_dir).glob('B*.npz'))
    packs = []
    for n in names:
        with np.load(Path(packs_dir) / f'{n}.npz') as z:
            n = z['ecg'].size              # a channel the pack lacks (e.g. no ABP) is all-missing
            packs.append({k: z[k].astype(np.float32) if k in z.files else np.full(n, np.nan, np.float32)
                          for k in KEYS})
    per = -(-beds // len(packs))
    plan = []                                  # (pack index, start sample) per bed
    for j in range(beds):
        p = packs[j % len(packs)]
        n = p['ecg'].size
        span = n - WIN - STEP * ticks
        plan.append((j % len(packs), int(span * ((j // len(packs)) / per))))
    types = ('ASYSTOLE', 'BRADY', 'TACHY', 'VFIB', 'VTACH')
    codes = np.array([types[j % len(types)] for j in range(beds)])
    out = []
    for t in range(ticks):
        b = {k: np.empty((beds, WIN), np.float32) for k in KEYS}
        for j, (pi, st) in enumerate(plan):
            for k in KEYS:
                b[k][j] = packs[pi][k][st + t * STEP: st + t * STEP + WIN]
        for k in KEYS:
            b['has_' + k] = np.isfinite(b[k]).any(1)
        b['code'] = codes
        out.append(b)
    return out, names, plan


def proc_stat():
    with open('/proc/stat') as f:
        v = [int(x) for x in f.readline().split()[1:]]
    idle = v[3] + (v[4] if len(v) > 4 else 0)
    return sum(v), idle


def ward(model, tick_batches, period_s, ncpu):
    for _ in range(5):                         # warm-up at this batch shape
        score(model, tick_batches[0])
    lat, cpu = [], []
    s0 = proc_stat(); w0 = time.perf_counter(); c00 = time.process_time()
    next_t = time.perf_counter()
    for b in tick_batches:
        next_t += period_s
        c0 = time.process_time(); t0 = time.perf_counter()
        score(model, b)
        lat.append((time.perf_counter() - t0) * 1000); cpu.append(time.process_time() - c0)
        time.sleep(max(0.0, next_t - time.perf_counter()))
    wall = time.perf_counter() - w0
    s1 = proc_stat()
    tot, idle = s1[0] - s0[0], s1[1] - s0[1]
    proc_cpu = time.process_time() - c00
    return {'ticks': len(lat), 'period_s': period_s, 'beds': int(tick_batches[0]['ecg'].shape[0]),
            'latency_ms': stats(lat), 'latency_pct_of_tick_p95': pct(lat, 95) / (period_s * 1000) * 100,
            'cpu_s_per_tick': stats(cpu),
            'process_cpu_pct_of_one_core': proc_cpu / wall * 100,
            'process_cpu_pct_of_guest': proc_cpu / wall / ncpu * 100,
            'guest_cpu_left_for_brain_pct': 100 - proc_cpu / wall / ncpu * 100,
            'guest_busy_pct_all_processes': (1 - idle / tot) * 100 if tot else None,
            'wall_s': wall}


def run(a):
    import torch
    from .model import ChipModel
    ncpu = os.cpu_count()
    model = ChipModel(device=a.device)
    with np.load(a.windows) as z:
        d = {k: z[k] for k in z.files if k in KEYS or k in ('has_ecg', 'has_ppg', 'has_abp', 'code')}
    hi = np.flatnonzero(np.load(a.mask))
    codes = d['code'].astype(str)
    batches = [int(x) for x in a.batches.split(',')]
    threads = sorted({1, ncpu})
    res = {'device': model.device, 'model': model.meta['model'], 'sha256': model.sha256,
           'host': platform.node(), 'machine': platform.machine(), 'torch': torch.__version__,
           'cpu_count': ncpu, 'heldout_windows': int(hi.size), 'micro': {}, 'ward': {}}
    try:
        import torch_nnpa
        res['torch_nnpa'] = getattr(torch_nnpa, '__version__', 'present')
    except Exception:
        res['torch_nnpa'] = None
    tw = ward_windows(a.packs, a.ward_beds, a.ward_ticks) if a.ward_ticks else None
    if tw:
        res['ward_packs'] = tw[1]
        res['ward_plan'] = [[tw[1][pi], st] for pi, st in tw[2]]
    for th in threads:
        torch.set_num_threads(th)
        print(f'# {model.device} threads={th}', flush=True)
        res['micro'][str(th)] = micro(model, d, hi, codes, batches, a.warmup, a.iters)
        if tw:
            res['ward'][str(th)] = ward(model, tw[0], a.period, ncpu)
            print(json.dumps({'ward_threads': th, **{k: res['ward'][str(th)][k] for k in
                              ('latency_ms', 'process_cpu_pct_of_guest')}}), flush=True)
    torch.set_num_threads(ncpu)
    sc = parity_scores(model, d, hi, codes, batches)
    np.savez(Path(a.out).with_suffix('.scores.npz'), **sc)
    json.dump(res, open(a.out, 'w'), indent=1)


def merge(a):
    cpu, nn = json.load(open(a.cpu)), json.load(open(a.nnpa))
    sc = np.load(Path(a.cpu).with_suffix('.scores.npz'))
    sn = np.load(Path(a.nnpa).with_suffix('.scores.npz'))
    ref = np.load(a.ref) if a.ref else None
    par = {}
    for k in sn.files:
        par[k] = {'max_abs_nnpa_minus_cpu': float(np.abs(sn[k] - sc[k]).max()),
                  'mean_abs_nnpa_minus_cpu': float(np.abs(sn[k] - sc[k]).mean())}
        if ref is not None:
            par[k]['max_abs_nnpa_minus_training'] = float(np.abs(sn[k] - ref).max())
            par[k]['max_abs_cpu_minus_training'] = float(np.abs(sc[k] - ref).max())
    table = []
    for th in cpu['micro']:
        for rc, rn in zip(cpu['micro'][th], nn['micro'][th]):
            table.append({'threads': int(th), 'batch': rc['batch'],
                          'cpu_median_ms': rc['total_ms']['median'], 'cpu_p95_ms': rc['total_ms']['p95'],
                          'nnpa_median_ms': rn['total_ms']['median'], 'nnpa_p95_ms': rn['total_ms']['p95'],
                          'cpu_windows_per_s': rc['windows_per_s'], 'nnpa_windows_per_s': rn['windows_per_s'],
                          'nnpa_over_cpu_median': rn['total_ms']['median'] / rc['total_ms']['median'],
                          'cpu_device_ms': rc['device_ms']['median'], 'nnpa_device_ms': rn['device_ms']['median'],
                          'max_abs_nnpa_minus_cpu': par[str(rc['batch'])]['max_abs_nnpa_minus_cpu']})
    out = {'what': 'CNN input scaling + forward, batched, nnpa:0 vs cpu (sw_chip.batch_bench)',
           'cpu': cpu, 'nnpa': nn, 'parity_heldout': par, 'table': table}
    json.dump(out, open(a.out, 'w'), indent=1)
    for r in table:
        print(json.dumps({k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()}))


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    r = sub.add_parser('run')
    r.add_argument('--device', required=True, choices=('nnpa', 'cpu'))
    r.add_argument('--windows', required=True); r.add_argument('--mask', required=True)
    r.add_argument('--packs', required=True); r.add_argument('--out', required=True)
    r.add_argument('--batches', default=','.join(map(str, BATCHES)))
    r.add_argument('--warmup', type=int, default=30); r.add_argument('--iters', type=int, default=200)
    r.add_argument('--ward-beds', type=int, default=96); r.add_argument('--ward-ticks', type=int, default=12)
    r.add_argument('--period', type=float, default=5.0)
    m = sub.add_parser('merge')
    m.add_argument('cpu'); m.add_argument('nnpa'); m.add_argument('out'); m.add_argument('--ref', default=None)
    a = ap.parse_args(argv)
    run(a) if a.cmd == 'run' else merge(a)


if __name__ == '__main__':
    main()
