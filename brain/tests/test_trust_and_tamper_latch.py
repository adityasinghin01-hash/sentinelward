"""Offline trust and the tampering latch (live judged run, items 1 and 3)."""
import json

import pytest

from sw_brain.decision import decide
from sw_brain.io import MemoryBus
from sw_brain.service import BrainService, TAMPER_RELEASE_MS


def clean(**over):
    results = {f'M{i}': {'score': .05, 'reason': 'clean', 'extra': {'eligible': True}} for i in range(1, 7)}
    for model, value in over.items():
        results[model] = ({'score': None, 'reason': 'waiting', 'extra': {'eligible': False}} if value is None else
                          {'score': value, 'reason': f'{model} suspicious', 'extra': {'eligible': True, 'independent_evidence': True}})
    return results


class Scripted:
    """Detector suite whose results are chosen by the test for each tick."""
    def __init__(self):
        self.next = clean()
    def evaluate(self, window, state, now_ms):
        return self.next
    def reset(self):
        self.next = clean()


def setup(frame, seconds=10):
    suite = Scripted()
    service = BrainService(MemoryBus(), suite=suite)
    feed(service, frame, 0, seconds)
    return service, suite


def feed(service, frame, start, end, **updates):
    for i in range(start, end):
        service.receive('ward/bed/B01/vitals', json.dumps(frame(i, **updates)), received_ms=i*1000)


def offline_results():
    return clean(M1=None, M2=None, M3=None, M4=None, M5=None, M6=None)


def test_offline_monitor_has_zero_trust_and_says_so(frame):
    service, suite = setup(frame)
    assert service.tick(10000)[0]['verdict'] == 'NORMAL'
    trusted_at = service.beds['B01'].last_trusted_ts
    suite.next = offline_results()
    verdict = service.tick(15000)[0]
    assert verdict['verdict'] == 'UNSURE'
    assert verdict['trust'] == 0.
    assert 'offline' in verdict['reasons'][0] and 'trust 0' in verdict['reasons'][0]
    # last_trusted_ts still points at the last NORMAL verdict.
    assert verdict['last_trusted_ts'] == trusted_at == 10000


@pytest.mark.parametrize('alarm', [False, True])
def test_decide_offline_never_reports_numeric_full_trust(alarm):
    verdict = decide('B01', 0, 10000, offline_results(), alarm=alarm, offline=True, last_trusted_ts=5000)
    assert verdict['trust'] == 0.
    assert verdict['last_trusted_ts'] == 5000
    assert any('offline' in r and 'trust 0' in r for r in verdict['reasons'])
    assert verdict['verdict'] == ('EMERGENCY' if alarm else 'UNSURE')


def test_online_without_eligible_checks_keeps_previous_trust_rule():
    verdict = decide('B01', 0, 10000, offline_results())
    assert verdict['verdict'] == 'UNSURE' and verdict['trust'] == 1.


def test_both_stays_both_after_cut_off_then_tampering_offline(frame):
    service, suite = setup(frame)
    service.receive('ward/bed/B01/vitals', json.dumps(frame(9, monitor_alarm={'code': 'ASYSTOLE', 'priority': 'high'})), received_ms=9500)
    suite.next = clean(M4=.98, M5=.9)
    first = service.tick(10000)[0]
    assert first['verdict'] == 'BOTH'
    # Cut off: silent monitor, every check n/a, alarm hold still active.
    suite.next = offline_results()
    held = service.tick(20000)[0]
    assert held['verdict'] == 'BOTH' and held['priority'] == 'high'
    assert held['reasons'][0] == 'Monitor alarm remains active'
    assert held['reasons'][1] == 'M4 suspicious'
    assert held['trust'] == 0.
    # Alarm hold expired, still silent: the emergency is never downgraded while tampering is latched.
    later = service.tick(120000)[0]
    assert later['verdict'] == 'BOTH' and later['trust'] == 0.
    assert later['reasons'][0] == 'Emergency held until a bedside check: Monitor alarm remains active'
    assert later['reasons'][1] == 'M4 suspicious'
    # A bedside patient_ok ends the emergency; the silent monitor stays TAMPERING, never UNSURE/NORMAL.
    service.receive('ward/bed/B01/bedside', json.dumps({'v': 1, 'type': 'bedside_check', 'bed_id': 'B01', 'ts': 121000,
                    'result': 'patient_ok', 'by': 'staff:nurse'}), received_ms=121000)
    after = service.tick(125000)[0]
    assert after['verdict'] == 'TAMPERING' and after['trust'] == 0.
    assert after['reasons'][0] == 'M4 suspicious'
    assert 'offline' in after['reasons'][1] and 'tampering' in after['reasons'][1]


def test_live_tampering_after_alarm_expiry_stays_both(frame):
    service, suite = setup(frame)
    service.receive('ward/bed/B01/vitals', json.dumps(frame(9, monitor_alarm={'code': 'VFIB', 'priority': 'high'})), received_ms=9500)
    suite.next = clean(M4=.98)
    assert service.tick(10000)[0]['verdict'] == 'BOTH'
    feed(service, frame, 10, 100)
    assert service.tick(100000)[0]['verdict'] == 'BOTH'


def test_latched_tampering_upgrades_a_new_emergency_never_downgrades(frame):
    service, suite = setup(frame)
    suite.next = clean(M3=.95, M5=.95)
    assert service.tick(10000)[0]['verdict'] == 'TAMPERING'
    suite.next = offline_results()
    assert service.tick(15000)[0]['verdict'] == 'TAMPERING'
    feed(service, frame, 15, 20, monitor_alarm={'code': 'VTACH', 'priority': 'high'})
    suite.next = clean()
    verdict = service.tick(20000)[0]
    assert verdict['verdict'] == 'BOTH'
    assert verdict['reasons'][:2] == ['Monitor alarm remains active', 'M3 suspicious']


def test_back_online_needs_30_s_of_clean_live_data(frame):
    service, suite = setup(frame)
    suite.next = clean(M4=.99)
    assert service.tick(10000)[0]['verdict'] == 'TAMPERING'
    suite.next = offline_results()
    assert service.tick(15000)[0]['verdict'] == 'TAMPERING'
    # Undo: monitor back online and every check clean.
    suite.next = clean()
    seen = []
    for now in range(105000, 160000, 5000):
        feed(service, frame, now//1000-5, now//1000)
        verdict = next(v for v in service.tick(now) if v['bed_id'] == 'B01')
        seen.append((now, verdict['verdict']))
        if verdict['verdict'] == 'TAMPERING':
            assert verdict['trust'] == 0.
            assert verdict['reasons'][-1].startswith('Earlier tampering evidence held')
            assert verdict['last_trusted_ts'] is None  # held windows never count as trusted
    first_normal = next(now for now, label in seen if label == 'NORMAL')
    assert first_normal - 105000 >= TAMPER_RELEASE_MS
    assert all(label == 'TAMPERING' for now, label in seen if now < first_normal)
    assert all(label == 'NORMAL' for now, label in seen if now >= first_normal)
    assert service.beds['B01'].tamper_latch is None


def test_unclean_window_restarts_the_release_clock(frame):
    service, suite = setup(frame)
    suite.next = clean(M4=.99)
    service.tick(10000)
    suite.next = offline_results()
    service.tick(15000)
    suite.next = clean()
    def at(now):
        feed(service, frame, now//1000-5, now//1000)
        return service.tick(now)[0]['verdict']
    at(105000); at(110000); at(115000); at(120000); at(125000)
    suite.next = clean(M3=.6)  # one inconclusive window
    assert at(130000) == 'TAMPERING'
    suite.next = clean()
    for now in range(135000, 165000, 5000):
        assert at(now) == 'TAMPERING'
    assert at(165000) == 'NORMAL'


def test_patient_ok_alone_does_not_release_a_silent_monitor(frame):
    service, suite = setup(frame)
    suite.next = clean(M4=.99)
    service.tick(10000)
    suite.next = offline_results()
    service.receive('ward/bed/B01/bedside', json.dumps({'v': 1, 'type': 'bedside_check', 'bed_id': 'B01', 'ts': 12000,
                    'result': 'patient_ok', 'by': 'staff:nurse'}), received_ms=12000)
    assert service.tick(60000)[0]['verdict'] == 'TAMPERING'


def test_attack_ending_on_a_clean_online_monitor_releases_at_once(frame):
    # B05: the replay stops and the very next window is clean with eligible checks.
    service, suite = setup(frame, 20)
    suite.next = clean(M4=.99)
    assert service.tick(10000)[0]['verdict'] == 'TAMPERING'
    suite.next = clean()
    assert service.tick(15000)[0]['verdict'] == 'NORMAL'


@pytest.mark.parametrize('cmd', ['reset', 'run'])
def test_demo_controls_release_the_latch(frame, cmd):
    service, suite = setup(frame)
    suite.next = clean(M4=.99)
    service.tick(10000)
    suite.next = offline_results()
    assert service.tick(15000)[0]['verdict'] == 'TAMPERING'
    service.receive('ward/demo/control', json.dumps({'v': 1, 'type': 'demo_control', 'ts': 16000, 'cmd': cmd,
                    'run_id': 'r2', 'start_at_s': 0}), received_ms=16000)
    feed(service, frame, 17, 30)
    suite.next = clean()
    assert service.tick(30000)[0]['verdict'] == 'NORMAL'
