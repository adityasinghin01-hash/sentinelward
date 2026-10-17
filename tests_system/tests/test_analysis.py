"""Synthetic integration cases for the result tables and safety checks."""
from tests_system.metrics import analyze_t8, blind_time, row
from tests_system.reporting import summary, write_report
from tests_system.smoke_h6 import analyze as analyze_smoke
from tests_system.tests.test_metrics import bus


def event(kind, ts, bed=None, **detail):
    return {'event': kind, 'ts': ts, 't_s': (ts - 1000000) / 1000, 'bed_id': bed, 'detail': detail}


def whole_run():
    return [event('run_start', 1000000, origin_ms=1000000), event('run_end', 2200000, reason='complete')]


def get(rows, name):
    return next(r for r in rows if r['name'] == name)


def test_summary_never_fills_a_missing_third_run():
    reports = [{'rows': [row('delay', 'PASS', 2)]}, {'rows': [row('delay', 'PASS', 4)]}]
    assert get(summary(reports), 'delay mean')['status'] == 'NOT RUN'
    reports.append({'rows': [row('delay', 'FAIL', 24)]})
    assert get(summary(reports), 'delay mean')['value'] == 10
    assert get(summary(reports), 'delay max')['value'] == 24


def test_missing_attack_log_does_not_publish_a_guessed_blind_time():
    results = analyze_t8(whole_run(), [], [], [])
    assert get(results, 'Total Blind Time with SentinelWard s')['value'] is None
    assert get(results, 'B05 time-to-safe s')['status'] == 'NOT RUN'
    assert get(results, 'Monitor alarms including forged')['status'] == 'NOT RUN'


def test_b07_cancel_before_ack_fails():
    messages = [bus('alert', 'B07', 1850000, alert_id='a', status='open', priority='high', to=['staff:priya']),
                bus('alert', 'B07', 1860000, alert_id='a', status='closed', priority='high', to=['staff:priya'])]
    result = get(analyze_t8(whole_run(), [], messages, []), 'B07 high alert preserved until ack')
    assert result['status'] == 'FAIL'
    assert result['evidence'][0]['recv_ms'] == 1860000


def test_alert_acknowledgement_prevents_false_cancel_failure():
    messages = [bus('alert', 'B07', 1850000, alert_id='a', status='open', priority='high', to=['staff:priya']),
                bus('alert', 'B07', 1860000, alert_id='a', status='closed', priority='high', to=['staff:priya'],
                    acked_by='staff:priya', acked_ts=1859000)]
    assert get(analyze_t8(whole_run(), [], messages, []), 'B07 high alert preserved until ack')['status'] == 'PASS'


def test_duplicate_alert_updates_count_once():
    messages = [bus('alert', 'B03', 1300000 + i, alert_id='same', priority='high', to=['staff:priya']) for i in range(3)]
    assert get(analyze_t8(whole_run(), [], messages, []), 'Nurse alerts sent')['value'] == 1


def test_undo_requires_reference_to_observed_cutoff():
    messages = [bus('action', 'B05', 1601000, action_id='cut', action='disable_client', result='ok', device_id='MON-05'),
                bus('action', 'B05', 1930000, action_id='undo', action='enable_client', result='ok', undoes='someone-else')]
    polls = [{'recv_ms': 1931000, 'data': {'beds': [{'bed_id': 'B05', 'display': 'live'}]}}]
    assert get(analyze_t8(whole_run(), [], messages, polls), 'B05 undo restores live display')['status'] == 'FAIL'
    messages[1]['message']['undoes'] = 'cut'
    assert get(analyze_t8(whole_run(), [], messages, polls), 'B05 undo restores live display')['status'] == 'PASS'


def test_unmonitored_seconds_after_handcheck_are_excluded():
    messages = [bus('alert', 'B05', 1000, priority='medium', to=['staff:priya'])]
    assert blind_time(messages, [], 'B05', 1000, 7000, [])['with_s'] == 0


def test_incomplete_run_prevents_passing_aggregate():
    events = [event('run_start', 1000000, origin_ms=1000000)]
    results = analyze_t8(events, [], [], [])
    assert get(results, 'Nurse alerts sent')['status'] == 'NOT RUN'
    assert get(results, 'Missed emergencies by deadline')['value'] is None


def test_report_writes_honest_json_and_markdown(tmp_path):
    import json
    write_report(tmp_path, 'demo', [row('Blind Time', 'NOT RUN', reason='Attack end absent')])
    doc = json.loads((tmp_path / 'demo_results.json').read_text())
    assert doc['rows'][0]['value'] is None
    assert 'Attack end absent' in (tmp_path / 'demo_results.md').read_text()


def test_smoke_source_lifetime_is_sixty_not_seventyfive_frames():
    messages = [dict(bus('vitals', 'B03', 1270000 + i * 1000, seq=i + 1,
                         monitor_alarm={'code': 'VTACH'} if i == 30 else None), size_bytes=3100)
                for i in range(60)]
    events = [event('run_start', 1270000, origin_ms=1000000)]
    rows = analyze_smoke(messages, [], [], events)
    assert get(rows, 'Vitals count, sequence, validation')['status'] == 'PASS'
    assert get(rows, 'VTACH at T+05:00 ±1 s')['status'] == 'PASS'


def test_no_telemetry_does_not_prove_zero_missed_emergencies():
    results = analyze_t8(whole_run(), [event('attack_start', 1600000, 'B05')], [], [])
    assert get(results, 'Missed emergencies by deadline')['status'] == 'NOT RUN'


def test_emergency_preservation_both_still_counts_attack_as_caught():
    attacks = [event('attack_start', 1960000, 'B06'), event('attack_end', 2200000, 'B06')]
    messages = [bus('verdict', 'B06', 1965000, verdict='BOTH')]
    results = analyze_t8(whole_run(), attacks, messages, [])
    assert get(results, 'B06 attack detection delay s')['value'] == 5
    assert get(results, 'Attacks caught')['status'] == 'NOT RUN'  # other actual starts missing


def test_future_or_stale_emergency_is_not_correlated_to_a_different_event():
    events = whole_run() + [event('monitor_alarm', 1300000, 'B03')]
    messages = [bus('verdict', 'B03', 1305000, verdict='EMERGENCY')]
    messages[0]['message']['window_start'] = 1100000  # old inference redelivered after alarm
    result = get(analyze_t8(events, [], messages, []), 'B03 EMERGENCY')
    assert result['status'] == 'FAIL'


def test_b11_zero_definition_requires_that_episode_to_have_run():
    result = get(analyze_t8(whole_run(), [event('attack_start', 1600000, 'B05')], [], []), 'B11 hidden time with s')
    assert result['status'] == 'NOT RUN' and result['value'] is None


def test_b05_cutoff_cannot_precede_tampering_verdict():
    messages = [bus('action', 'B05', 1601000, action_id='cut', action='disable_client', result='ok', device_id='MON-05'),
                bus('verdict', 'B05', 1602000, verdict='TAMPERING'),
                bus('action', 'B05', 1930000, action_id='undo', action='enable_client', result='ok', undoes='cut')]
    assert get(analyze_t8(whole_run(), [], messages, []), 'B05 verdict before cut-off')['status'] == 'FAIL'


def test_corrupt_bus_line_cannot_prove_no_false_alerts():
    messages = [bus('verdict', 'B01', 1005000, verdict='NORMAL')]
    result = get(analyze_t8(whole_run(), [], messages, [], ['bus.jsonl:5: ValueError']), 'B01 no false alerts')
    assert result['status'] == 'NOT RUN'


def test_summary_excludes_partial_runs_even_when_they_have_numbers():
    reports = [{'rows': [row('delay', 'FAIL', 2)], 'complete': False},
               {'rows': [row('delay', 'PASS', 4)]}, {'rows': [row('delay', 'PASS', 6)]}]
    assert get(summary(reports), 'delay mean')['value'] is None


def test_both_preserves_emergency_detection_even_if_strict_verdict_differs():
    messages = [bus('verdict', 'B03', 1305000, verdict='BOTH'),
                bus('verdict', 'B09', 1520000, verdict='BOTH'),
                bus('verdict', 'B07', 1845000, verdict='EMERGENCY')]
    rows = analyze_t8(whole_run(), [], messages, [])
    assert get(rows, 'Missed emergencies by deadline')['value'] == 0
    assert get(rows, 'B03 EMERGENCY')['status'] == 'FAIL'  # strict specificity stays visible


def test_no_run_evidence_is_not_run_not_a_failed_clinical_test():
    results = analyze_t8([], [], [], [], ['Missing simulator events.jsonl'])
    assert all(r['status'] == 'NOT RUN' and r['value'] is None for r in results)
