"""Hostile review: safety inputs must work even without monitor telemetry."""
import json

from sw_brain.io import MemoryBus
from sw_brain.service import BrainService


def test_patient_not_ok_without_vitals_still_publishes_emergency():
    service = BrainService(MemoryBus())
    check = {'v': 1, 'type': 'bedside_check', 'bed_id': 'B07',
             'ts': 20000, 'by': 'staff:priya', 'result': 'patient_not_ok', 'notes': ''}
    assert service.receive('ward/bed/B07/bedside', json.dumps(check), received_ms=20000)
    verdicts = service.tick(25000)
    assert len(verdicts) == 1
    assert verdicts[0]['verdict'] == 'EMERGENCY'
    assert verdicts[0]['priority'] == 'high'


def test_reset_rejects_pre_reset_queued_alarm_and_delayed_bedside(frame):
    service = BrainService(MemoryBus())
    control = {'v': 1, 'type': 'demo_control', 'ts': 20000, 'cmd': 'reset',
               'run_id': 'reset', 'start_at_s': 0}
    assert service.receive('ward/demo/control', json.dumps(control), received_ms=20000)
    old_alarm = frame(10, monitor_alarm={'code': 'VFIB', 'priority': 'high'})
    assert not service.receive('ward/bed/B01/vitals', json.dumps(old_alarm), received_ms=10000)
    old_check = {'v': 1, 'type': 'bedside_check', 'bed_id': 'B07',
                 'ts': 10000, 'by': 'staff:priya', 'result': 'patient_not_ok', 'notes': ''}
    assert not service.receive('ward/bed/B07/bedside', json.dumps(old_check), received_ms=21000)
    assert service.tick(25000) == []
