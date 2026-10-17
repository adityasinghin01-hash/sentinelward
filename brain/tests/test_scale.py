"""Configurable bed set (SW_BRAIN_MAX_BED) and bounded per-bed history."""
import json
import os
import subprocess
import sys

import pytest

from sw_brain import io
from sw_brain.io import MemoryBus, decode, max_bed_from_env, set_max_bed
from sw_brain.service import HISTORY_LOOKBACK_MS, HISTORY_MARGIN_MS, WINDOWS_KEPT, BrainService
from sw_brain.windows import VitalsWindowAssembler


@pytest.fixture
def max_bed():
    """Change the accepted bed set for one test, then restore the ward default."""
    yield set_max_bed
    set_max_bed(io.WARD_MAX_BED)


def vitals_topic(bed):
    return f'ward/bed/{bed}/vitals'


def test_default_is_the_ward_b01_to_b12(frame):
    assert max_bed_from_env({}) == 12
    assert io.BEDS == {f'B{i:02d}' for i in range(1, 13)}
    assert io.DEVICES == {f'MON-{i:02d}' for i in range(1, 13)}
    decode(vitals_topic('B12'), json.dumps(frame(bed='B12')))
    with pytest.raises(ValueError, match='Expected ward bed'):
        decode(vitals_topic('B13'), json.dumps(frame(bed='B13')))


@pytest.mark.parametrize('raw,expected', [('', 12), ('  ', 12), ('24', 24), ('96', 96), ('99', 99), ('1', 1)])
def test_env_parsing(raw, expected):
    assert max_bed_from_env({'SW_BRAIN_MAX_BED': raw}) == expected


@pytest.mark.parametrize('raw', ['0', '100', '-1', 'x', '12.5', '1e2'])
def test_env_rejects_values_outside_the_contract(raw):
    with pytest.raises(ValueError, match='SW_BRAIN_MAX_BED'):
        max_bed_from_env({'SW_BRAIN_MAX_BED': raw})


def test_env_is_read_at_import():
    code = 'from sw_brain import io; print(len(io.BEDS), "MON-48" in io.DEVICES, "B49" in io.BEDS)'
    env = {**os.environ, 'SW_BRAIN_MAX_BED': '48'}
    out = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True, check=True)
    assert out.stdout.split() == ['48', 'True', 'False']
    bad = subprocess.run([sys.executable, '-c', code], env={**env, 'SW_BRAIN_MAX_BED': '100'},
                         capture_output=True, text=True)
    assert bad.returncode != 0 and 'SW_BRAIN_MAX_BED' in bad.stderr


def test_raised_limit_scores_extra_beds_end_to_end(frame, max_bed):
    max_bed(24)
    bus = MemoryBus(); service = BrainService(bus)
    for sec in range(10):
        for bed in ('B01', 'B13', 'B24'):
            assert service.receive(vitals_topic(bed), json.dumps(frame(sec, bed=bed)), received_ms=sec*1000)
    with pytest.raises(ValueError, match='Expected ward bed'):
        decode(vitals_topic('B25'), json.dumps(frame(bed='B25')))
    assert not service.receive(vitals_topic('B25'), json.dumps(frame(bed='B25')), received_ms=1000)
    verdicts = service.tick(10000)
    assert sorted(v['bed_id'] for v in verdicts) == ['B01', 'B13', 'B24']
    assert service.tick_stats['verdicts'] == 3 and service.tick_stats['beds'] == 3
    assert any(t == 'ward/bed/B24/verdict' for t, *_ in bus.published)
    net = {'v': 1, 'type': 'net_features', 'device_id': 'MON-24', 'window_start': 0, 'window_s': 5,
           'msgs_per_s': 1, 'bytes_per_s': 1, 'iat_mean_ms': 1, 'iat_std_ms': 0, 'payload_mean': 1,
           'payload_std': 0, 'senders': 1, 'connects_per_s': 0, 'malformed': 0, 'seq_gaps': 0,
           'seq_repeats': 0, 'stale_ms': 0}
    assert service.receive('net/device/MON-24/features', json.dumps(net), received_ms=11000)
    net25 = {**net, 'device_id': 'MON-25'}
    assert not service.receive('net/device/MON-25/features', json.dumps(net25), received_ms=11000)
    service.reset()
    assert bus.cleared == [f'ward/bed/B{i:02d}/verdict' for i in range(1, 25)]


def test_device_must_be_within_the_accepted_monitors(frame, max_bed):
    max_bed(24)
    assembler = VitalsWindowAssembler()
    assembler.ingest(frame(0, bed='B24'))
    with pytest.raises(ValueError, match='device_id'):
        assembler.ingest(frame(1, bed='B24', device_id='MON-25'))
    max_bed(12)
    with pytest.raises(ValueError, match='bed_id'):
        assembler.ingest(frame(2, bed='B13'))


def test_lowered_limit_rejects_beds_above_it(frame, max_bed):
    max_bed(4)
    with pytest.raises(ValueError, match='Expected ward bed'):
        decode(vitals_topic('B05'), json.dumps(frame(bed='B05')))


def test_history_is_bounded_by_the_longest_lookback(frame):
    service = BrainService(MemoryBus())
    cuff = {'ts': 10000, 'sys': 90, 'dia': 40, 'map': 50}
    keep_ms = HISTORY_LOOKBACK_MS + HISTORY_MARGIN_MS
    for sec in range(0, 600):
        updates = {'nibp': cuff} if sec == 10 else {}
        service.receive(vitals_topic('B01'), json.dumps(frame(sec, **updates)), received_ms=sec*1000)
        state = service.beds['B01']
        assert state.messages[0]['received_ms'] >= sec*1000 - keep_ms
        if sec == 300:
            # The 290-s-old cuff is still visible to the 300-s readers (M6, cuff safety check).
            assert any(r['message'].get('nibp') for r in state.messages)
    assert len(state.messages) == keep_ms // 1000 + 1
    assert not any(r['message'].get('nibp') for r in state.messages)
    assert len(state.windows) == WINDOWS_KEPT
    # The tick still finds the window that starts 10 s before it.
    verdict = service.tick(600000)[0]
    assert verdict['window_start'] == 590000 and service.beds['B01'].windows[-1]['window_start'] == 590000
