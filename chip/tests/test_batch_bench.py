import json

import numpy as np
import pytest

torch = pytest.importorskip('torch')

from sw_chip import batch_bench as bb  # noqa: E402
from sw_chip.model import ChipModel  # noqa: E402
from sw_chip.parity import live_window  # noqa: E402


@pytest.fixture(scope='module')
def model():
    return ChipModel(device='cpu')


def fake_windows(n=10, seed=0):
    r = np.random.default_rng(seed)
    d = {k: r.normal(size=(n, 1250)).astype(np.float32) for k in bb.KEYS}
    d['abp'][::2] = np.nan
    d['has_ecg'] = np.ones(n, bool); d['has_ppg'] = np.ones(n, bool); d['has_abp'] = np.arange(n) % 2 == 1
    d['code'] = np.array(['VTACH', 'ASYSTOLE', 'VFIB', 'BRADY', 'TACHY'] * (n // 5))
    return d


def test_batched_score_equals_live_predict(model):
    d = fake_windows()
    p, *_ = bb.score(model, bb.take(d, np.arange(10), d['code']))
    one = [model.predict(live_window(d, i), d['code'][i])[0] for i in range(10)]
    assert np.allclose(p, one, atol=1e-5)


def test_ward_windows_from_packs(tmp_path):
    for i in range(3):
        kw = {'ecg': np.sin(np.arange(20000) / 10).astype(np.float32), 'ppg': np.ones(20000, np.float32)}
        if i == 0:
            kw['abp'] = np.full(20000, 80, np.float32)
        np.savez(tmp_path / f'B0{i + 1}.npz', **kw)
    ticks, names, plan = bb.ward_windows(tmp_path, beds=7, ticks=3)
    assert names == ['B01', 'B02', 'B03'] and len(plan) == 7 and len(ticks) == 3
    assert ticks[0]['ecg'].shape == (7, 1250)
    assert ticks[0]['has_abp'].tolist() == [True, False, False, True, False, False, True]
    st = plan[0][1]
    assert np.array_equal(ticks[1]['ecg'][0], np.sin(np.arange(st + 625, st + 1875) / 10).astype(np.float32))


def test_run_and_merge_cpu(tmp_path, model):
    d = fake_windows(10)
    np.savez(tmp_path / 'w.npz', **d)
    np.save(tmp_path / 'm.npy', np.ones(10, bool))
    (tmp_path / 'packs').mkdir()
    np.savez(tmp_path / 'packs' / 'B01.npz', ecg=np.zeros(20000, np.float32), ppg=np.ones(20000, np.float32))
    common = ['--windows', str(tmp_path / 'w.npz'), '--mask', str(tmp_path / 'm.npy'), '--packs', str(tmp_path / 'packs'),
              '--batches', '1,4', '--warmup', '1', '--iters', '2', '--ward-beds', '3', '--ward-ticks', '2', '--period', '0.01']
    for name in ('a', 'b'):     # two cpu runs stand in for cpu vs nnpa
        bb.main(['run', '--device', 'cpu', *common, '--out', str(tmp_path / f'{name}.json')])
    bb.main(['merge', str(tmp_path / 'a.json'), str(tmp_path / 'b.json'), str(tmp_path / 'out.json')])
    out = json.loads((tmp_path / 'out.json').read_text())
    assert {r['batch'] for r in out['table']} == {1, 4}
    assert all(r['max_abs_nnpa_minus_cpu'] < 1e-6 for r in out['table'])
    assert out['cpu']['ward']['1']['beds'] == 3 and out['cpu']['ward']['1']['ticks'] == 2
