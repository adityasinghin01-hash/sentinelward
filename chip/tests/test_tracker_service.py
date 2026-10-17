import json
import math

import pytest

from sw_chip.tracker import AlarmTracker, check_vitals
from sw_chip.service import ChipService, chip_topic

T0 = 1_760_000_000_000  # aligned to 5 s


def vit(sec, alarm=None, bed='B03', seq0=1, abp=False):
    ecg = [round(math.sin((sec * 125 + i) / 7.0), 3) for i in range(125)]
    m = {'v': 1, 'type': 'vitals', 'bed_id': bed, 'device_id': 'MON-' + bed[1:], 'seq': seq0 + sec,
         'ts': T0 + sec * 1000, 'fs': 125, 'ecg': ecg, 'ppg': [1.0] * 125, 'abp': [80.0] * 125 if abp else None,
         'hr': 80, 'spo2': 98, 'monitor_alarm': None}
    if alarm:
        m['monitor_alarm'] = {'code': alarm, 'priority': 'high'}
    return m


def feed(tr, msgs):
    return [tr.ingest(m, m['ts']) for m in msgs]


def test_new_alarm_with_full_prealarm_window():
    tr = AlarmTracker()
    out = feed(tr, [vit(s) for s in range(10)] + [vit(10, 'VTACH')])
    assert out[:10] == [None] * 10
    code, ts, w = out[10]
    assert (code, ts) == ('VTACH', T0 + 10000)
    assert w['window_start'] == T0 and len(w['ecg']) == 1250 and len(w['ppg']) == 1250 and w['abp'] is None
    assert w['ecg'][:125] == vit(0)['ecg']


def test_same_episode_scored_once_new_code_scored_again():
    tr = AlarmTracker()
    out = feed(tr, [vit(s) for s in range(10)] + [vit(s, 'VTACH') for s in range(10, 20)] + [vit(20, 'VFIB')])
    hits = [o for o in out if o]
    assert [h[0] for h in hits] == ['VTACH', 'VFIB']


def test_episode_continues_through_silent_seconds_within_hold():
    # Brain rule: same episode only for the same/next contiguous alarmed frame; a gap of quiet
    # seconds then the same code again is a new episode (and gets a window when 10 s are buffered).
    tr = AlarmTracker()
    msgs = [vit(s) for s in range(10)] + [vit(10, 'BRADY')] + [vit(s) for s in range(11, 21)] + [vit(21, 'BRADY')]
    hits = [o for o in feed(tr, msgs) if o]
    assert len(hits) == 2 and hits[1][2]['window_start'] == T0 + 11000


def test_no_window_without_ten_contiguous_seconds():
    tr = AlarmTracker()
    msgs = [vit(s) for s in range(5)] + [vit(s) for s in range(6, 12)] + [vit(12, 'ASYSTOLE')]
    assert not any(feed(tr, msgs))


def test_duplicate_frame_ignored_and_seq_restart_resets_bed():
    tr = AlarmTracker()
    feed(tr, [vit(s) for s in range(10)])
    assert tr.ingest(vit(9), T0 + 9000) is None           # duplicate
    assert tr.ingest(vit(10, 'VTACH'), T0 + 10000)         # still has its 10 s
    later = vit(40, seq0=-39)                              # seq back to 1, time moved on
    tr.ingest(later, later['ts'])
    assert len(tr.beds['B03'].chunks) == 1


def test_abp_kept_when_present():
    tr = AlarmTracker()
    out = feed(tr, [vit(s, abp=True) for s in range(10)] + [vit(10, 'BRADY', abp=True)])
    assert out[10][2]['abp'][0] == 80.0


def test_check_vitals_rejects_bad_input():
    good = vit(0)
    assert check_vitals('ward/bed/B03/vitals', good) is None
    assert check_vitals('ward/bed/B04/vitals', good)
    assert check_vitals('ward/bed/B03/vitals', {**good, 'fs': 250})
    assert check_vitals('ward/bed/B03/vitals', {**good, 'ecg': [1.0] * 10})
    assert check_vitals('ward/bed/B03/vitals', {**good, 'ecg': [float('nan')] * 125})
    assert check_vitals('ward/bed/B03/vitals', {**good, 'monitor_alarm': {'code': 'X', 'priority': 'high'}})


class _FakeModel:
    def message(self, bed_id, ts, code, window):
        return {'v': 1, 'bed_id': bed_id, 'ts': ts, 'alarm_code': code, 'p_real': 0.9, 'label': 'real',
                'threshold': 0.2, 'model': 'm', 'device': 'cpu', 'latency_ms': 1.0,
                'heldout_challenge_cinc': 0.623, 'heldout_challenge_vtac': 0.665}


def test_service_publishes_once_per_alarm_on_chip_topic():
    sent = []
    svc = ChipService(_FakeModel(), lambda t, p: sent.append((t, json.loads(p))) or True)
    for s in range(10):
        svc.on_vitals('ward/bed/B03/vitals', json.dumps(vit(s)), now_ms=T0 + s * 1000)
    svc.on_vitals('ward/bed/B03/vitals', b'not json', now_ms=T0)
    svc.on_vitals('ward/bed/B07/vitals', json.dumps(vit(10, 'VTACH')), now_ms=T0)   # wrong topic
    for s in range(10, 15):
        svc.on_vitals('ward/bed/B03/vitals', json.dumps(vit(s, 'VTACH')), now_ms=T0 + s * 1000)
    svc.drain()
    assert [t for t, _ in sent] == [chip_topic('B03')] == ['ward/chip/B03']
    assert sent[0][1]['ts'] == T0 + 10000
    assert svc.stats['invalid'] == 2 and svc.stats['published'] == 1


def test_service_survives_model_error():
    class Bad:
        def message(self, *a):
            raise RuntimeError('boom')
    svc = ChipService(Bad(), lambda t, p: pytest.fail('must not publish'))
    for s in range(10):
        svc.on_vitals('ward/bed/B03/vitals', json.dumps(vit(s)), now_ms=T0 + s * 1000)
    svc.on_vitals('ward/bed/B03/vitals', json.dumps(vit(10, 'VTACH')), now_ms=T0 + 10000)
    assert svc.drain() == [None] and svc.stats['errors'] == 1
