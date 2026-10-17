import json

import pytest

from sw_brain.io import MemoryBus
from sw_brain.service import BrainService


def control(service, cmd, ts=20000, run_id='test'):
    return service.receive('ward/demo/control', json.dumps({
        'v': 1, 'type': 'demo_control', 'ts': ts, 'cmd': cmd,
        'run_id': run_id, 'start_at_s': 0,
    }), received_ms=ts)


def feed(service, frame, start=0):
    for sec in range(start, start + 10):
        assert service.receive('ward/bed/B01/vitals', json.dumps(frame(sec)),
                               received_ms=sec * 1000)


def assert_published_tick(bus, verdicts):
    scores = [m for topic, m, _, _ in bus.published if '/score/' in topic]
    verdicts_on_wire = [m for topic, m, _, retain in bus.published
                        if topic.endswith('/verdict') and retain]
    assert len(scores) == 6
    assert {m['model'] for m in scores} == {'M1', 'M2', 'M3', 'M4', 'M5', 'M6'}
    assert len(verdicts) == 1
    assert verdicts_on_wire == verdicts
    assert {m['model']: m['score'] for m in scores} == verdicts[0]['scores']
    assert verdicts[0]['scores']['M1'] == 0.


def test_startup_without_run_control_scores_vitals(frame):
    bus = MemoryBus()
    service = BrainService(bus)
    feed(service, frame)
    assert_published_tick(bus, service.tick(10000))


@pytest.mark.parametrize('cmd', ['reset', 'run'])
def test_control_clears_memory_and_new_vitals_are_scored(frame, cmd):
    bus = MemoryBus()
    service = BrainService(bus)
    feed(service, frame)
    service.tick(10000)
    feed(service, frame, 10)
    assert service.tick(20000)[0]['scores']['M4'] >= .9
    assert service.suite.detectors['M3'].baselines['B01']
    assert service.receive('ward/bed/B01/vitals', json.dumps(
        frame(20, monitor_alarm={'code': 'VTACH', 'priority': 'high'})), received_ms=20000)

    assert control(service, cmd, ts=21000)
    assert not service.beds
    for model in ('M3', 'M6'):
        assert not service.suite.detectors[model].baselines
        assert not service.suite.detectors[model].seen
    assert not service.suite.detectors['M4'].history
    if cmd == 'run':
        assert service.active_run_id == 'test'
    assert service.snapshots['B01']['ts'] == 20000

    bus.published.clear()
    feed(service, frame, 30)
    verdicts = service.tick(40000)
    assert_published_tick(bus, verdicts)
    assert verdicts[0]['scores']['M4'] == 0.
    assert verdicts[0]['scores']['M3'] is not None  # Rate agreement is checked while the timing baseline warms.
    assert verdicts[0]['verdict'] == 'NORMAL'  # Previous alarm is gone and the fresh signals agree.


@pytest.mark.parametrize('cmd', ['reset', 'run'])
def test_control_during_evaluation_discards_inflight_results(frame, monkeypatch, cmd):
    bus = MemoryBus()
    service = BrainService(bus)
    feed(service, frame)
    evaluate = service.suite.evaluate

    def evaluate_then_control(window, state, now_ms):
        results = evaluate(window, state, now_ms)
        assert control(service, cmd)
        return results

    monkeypatch.setattr(service.suite, 'evaluate', evaluate_then_control)
    assert service.tick(10000) == []
    assert bus.published == []
    assert service.last_verdicts == {}
    assert service.last_tick_ms is None

    monkeypatch.setattr(service.suite, 'evaluate', evaluate)
    feed(service, frame, 30)
    assert_published_tick(bus, service.tick(40000))


def test_reset_during_publication_discards_remaining_results(frame, monkeypatch):
    bus = MemoryBus()
    service = BrainService(bus)
    feed(service, frame)
    publish = bus.publish

    def publish_then_reset(topic, message, **kwargs):
        published = publish(topic, message, **kwargs)
        if len(bus.published) == 1:
            assert control(service, 'reset')
        return published

    monkeypatch.setattr(bus, 'publish', publish_then_reset)
    assert service.tick(10000) == []
    assert len(bus.published) == 1  # Only the score sent before reset.
    assert service.last_verdicts == {}
    assert service.last_tick_ms is None


def test_reset_allows_same_run_id_again(frame):
    service = BrainService(MemoryBus())
    assert control(service, 'run', ts=0)
    feed(service, frame)
    assert control(service, 'reset')
    assert control(service, 'run', ts=21000)
    assert service.active_run_id == 'test'
    assert not service.beds
