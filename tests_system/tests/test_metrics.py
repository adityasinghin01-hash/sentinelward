"""Hand-calculated cases: missing evidence must never become a passing zero."""
import json
import pytest
from tests_system.metrics import (read_jsonl, percentile, first_after, time_to_safe,
                                  blind_time, never_blank, verdict_checks, resource_metrics)


def bus(kind, bed, ts, **fields):
    return {'recv_ms': ts, 'topic': 'ward/test', 'retained': False,
            'message': {'type': kind, 'bed_id': bed, 'ts': ts, **fields}}


def test_jsonl_reports_corruption_and_preserves_zero(tmp_path):
    path = tmp_path / 'events.jsonl'
    path.write_text('{"hr":0}\nnot-json\n{"hr":null}\n')
    rows, errors = read_jsonl(path)
    assert rows == [{'hr': 0}, {'hr': None}]
    assert len(errors) == 1 and ':2:' in errors[0]


def test_missing_jsonl_is_explicit(tmp_path):
    assert read_jsonl(tmp_path / 'absent')[1]


def test_percentile_interpolates_and_empty_is_unknown():
    assert percentile([0, 10, 20, 30], 95) == pytest.approx(28.5)
    assert percentile([], 50) is None


def test_retained_and_pre_event_verdicts_cannot_count():
    rows = [bus('verdict', 'B05', 900, verdict='TAMPERING'),
            {**bus('verdict', 'B05', 1100, verdict='TAMPERING'), 'retained': True},
            bus('verdict', 'B05', 1700, verdict='TAMPERING')]
    assert first_after(rows, 'B05', 1000, lambda m: m.get('verdict') == 'TAMPERING')['recv_ms'] == 1700


def test_time_to_safe_requires_both_and_successful_matching_device():
    rows = [bus('action', 'B05', 2000, action='disable_client', result='error', device_id='MON-05'),
            bus('action', 'B05', 3000, action='disable_client', result='ok', device_id='MON-05'),
            bus('alert', 'B05', 5000, priority='medium', to=['staff:priya'])]
    assert time_to_safe(rows, 'B05', 1000, 10000)['value'] == 4
    assert time_to_safe(rows[:2], 'B05', 1000, 10000)['status'] == 'FAIL'


def test_blind_time_sums_hidden_and_pre_alert_unmonitored_and_gap():
    polls = [{'recv_ms': t, 'data': {'beds': [{'bed_id': 'B05', 'display': 'last_trusted'}]}}
             for t in range(1000, 7001, 1000)]
    rows = [bus('alert', 'B05', 4000, priority='medium', to=['staff:priya'])]
    result = blind_time(rows, polls, 'B05', 1000, 7000, [(5000, 7000)])
    assert result['with_s'] == 6  # 3 hidden + 3 unmonitored before alert
    assert result['without_s'] == 8  # 6 episode + 2 recording gap


def test_missing_poll_coverage_does_not_invent_blind_time():
    result = blind_time([], [], 'B05', 1000, 7000, [])
    assert result['status'] == 'NOT RUN'
    assert result['without_s'] == 6  # baseline needs events, not HTTP observations


def test_never_blank_preserves_zero_and_ignores_unreceived_beds():
    rows = [bus('vitals', 'B05', 1000)]
    polls = [{'recv_ms': 2000, 'data': {'beds': [{'bed_id': 'B05', 'vitals': {'hr': 0}},
                                                         {'bed_id': 'B01', 'vitals': None}]}}]
    assert never_blank(rows, polls)['value'] == 0
    polls.append({'recv_ms': 3000, 'data': {'beds': []}})
    assert never_blank(rows, polls)['value'] == 1


def test_script_fallback_is_labelled_and_late_verdict_fails():
    events = [{'event': 'run_start', 'ts': 1000000, 't_s': 0,
               'detail': {'origin_ms': 1000000}},
              {'event': 'run_end', 'ts': 2200000, 't_s': 1200, 'detail': {'reason': 'complete'}}]
    rows = [bus('verdict', 'B03', 1320000, verdict='EMERGENCY')]
    row = next(r for r in verdict_checks(events, [], rows) if r['name'] == 'B03 EMERGENCY')
    assert row['status'] == 'FAIL' and row['value'] == 20
    assert 'script time' in row['reason']


def test_resource_delay_uses_window_end_not_verdict_timestamp():
    rows = [bus('verdict', 'B01', 13000, window_start=1000, verdict='NORMAL')]
    result = resource_metrics(rows, [], [])
    assert next(r for r in result if r['name'] == 'B01 verdict delay p50 ms')['value'] == 2000


def test_unobserved_safety_cannot_pass():
    assert never_blank([], [])['status'] == 'NOT RUN'


def test_jsonl_rejects_overflow_and_bad_event_timestamp(tmp_path):
    path = tmp_path / 'events.jsonl'
    path.write_text('{"value":1e309}\n{"event":"run_start","ts":"not-a-time"}\n')
    rows, errors = read_jsonl(path)
    assert rows == [] and len(errors) == 2
