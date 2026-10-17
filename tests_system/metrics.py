"""Pure, replayable metrics. Epoch milliseconds in, unrounded measurements out."""
from __future__ import annotations
import json
import math
from pathlib import Path

DEFINITIONS = [
    'With SentinelWard: hidden time = episode start → the first nurse alert for that bed (medium or high), plus unmonitored time = seconds the bed showed "last_trusted" or "offline" BEFORE a nurse had been told to hand-check.',
    'Without SentinelWard (a normal monitor): hidden time = episode start → episode end, because forged or drifted readings look real until the episode stops. Unmonitored time = the recording gaps the normal monitor would show blank.',
    'nobody notices until the episode ends',
    'B11 (network only, no forged readings) has 0 hidden time both ways.',
    'Automated nurse notification means MQTT receipt of ward/alert addressed to staff; actual Telegram delivery requires the manual H6 phone check.',
    'Poll intervals use left-hold integration, at 1 s resolution; gaps over 2.5 s make Blind Time NOT RUN. The two specified components are added even when they overlap.',
    'Alerts count distinct alert_id values addressed to staff, not ladder updates or QoS redeliveries. Alarms count simulator events plus distinct forged alarm occurrences in attack events; absent forged-alarm evidence makes the combined denominator NOT RUN.',
    'The alarms-stopped comparison is monitor alarms minus unique nurse alerts (can be negative); it is an alert-count comparison, not proof that an individual alarm was silenced.',
    'Reported Markdown/CSV numbers are rounded to 3 decimals only at rendering; JSON retains precision. Delays use MQTT receipt time minus ground-truth event time.',
]


def finite_float(text):
    value = float(text)
    if not math.isfinite(value):
        raise ValueError('Non-finite number')
    return value


def read_jsonl(path):
    rows, errors = [], []
    try:
        with Path(path).open() as f:
            for n, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line, parse_float=finite_float, parse_constant=lambda v: (_ for _ in ()).throw(ValueError(v)))
                    if not isinstance(obj, dict):
                        raise ValueError('expected object')
                    for key in ('ts', 'recv_ms', 't_s'):
                        if key in obj and (type(obj[key]) not in (int, float) or not math.isfinite(obj[key])):
                            raise ValueError('Invalid timestamp')
                    if 'event' in obj and ('ts' not in obj or 't_s' not in obj):
                        raise ValueError('Event lacks timestamp/script time')
                    rows.append(obj)
                except (ValueError, TypeError) as exc:
                    errors.append(f'{path}:{n}: {type(exc).__name__}')
    except OSError as exc:
        errors.append(f'{path}: {type(exc).__name__}')
    return rows, errors


def percentile(values, p):
    values = sorted(v for v in values if isinstance(v, (int, float)) and math.isfinite(v))
    if not values:
        return None
    pos = (len(values) - 1) * p / 100
    lo, hi = math.floor(pos), math.ceil(pos)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def row(name, status, value=None, reason='', evidence=None, owner=''):
    return dict(name=name, status=status, value=None if status == 'NOT RUN' else value, reason=reason, evidence=evidence or [], owner=owner)


def observed(rows):
    return sorted((r for r in rows if isinstance(r.get('message'), dict)
                   and isinstance(r.get('recv_ms'), (int, float)) and not r.get('retained')),
                  key=lambda r: r['recv_ms'])


def first_after(rows, bed, start, predicate, end=float('inf')):
    return next((r for r in observed(rows) if r['message'].get('bed_id') == bed
                 and start <= r['recv_ms'] <= end
                 and (r['message'].get('type') == 'vitals' or r['message'].get('ts', r['recv_ms']) >= start)
                 and (r['message'].get('type') != 'verdict' or
                      (r['message'].get('ts', r['recv_ms']) >= start and
                       r['message'].get('window_start', start) + 10000 >= start))
                 and predicate(r['message'])), None)


def nurse(m):
    return m.get('type') == 'alert' and m.get('priority') in ('medium', 'high') and any(
        isinstance(x, str) and x.startswith('staff:') for x in (m.get('to') or []))


def evidence(*rows):
    return [dict(recv_ms=r['recv_ms'], message=r['message']) for r in rows if r]


def time_to_safe(rows, bed, start, end):
    cut = first_after(rows, bed, start, lambda m: m.get('type') == 'action'
                      and m.get('action') == 'disable_client' and m.get('result') == 'ok'
                      and m.get('device_id') == 'MON-' + bed[1:], end)
    alert = first_after(rows, bed, start, nurse, end)
    if not cut or not alert:
        return row(f'{bed} time-to-safe s', 'FAIL', reason='Missing successful device cut-off or staff alert',
                   evidence=evidence(cut, alert))
    return row(f'{bed} time-to-safe s', 'PASS', (max(cut['recv_ms'], alert['recv_ms']) - start) / 1000,
               evidence=evidence(cut, alert))


def bed_entries(poll):
    data = poll.get('data')
    return data.get('beds', []) if isinstance(data, dict) else []


def latest(bed):
    return bed.get('latest') if 'latest' in bed else bed.get('vitals')


def verdict_value(message):
    v = message.get('verdict')
    return v.get('verdict') if isinstance(v, dict) else v


def never_blank(rows, polls):
    first = {}
    for r in observed(rows):
        if r['message'].get('type') == 'vitals':
            first.setdefault(r['message'].get('bed_id'), r['recv_ms'])
    violations, checked = [], 0
    for poll in polls:
        if not isinstance(poll.get('data'), dict):
            continue
        beds = {b['bed_id']: b for b in bed_entries(poll)}
        for bed, start in first.items():
            if poll['recv_ms'] > start:
                checked += 1
                values = latest(beds.get(bed, {}))
                if values is None or not isinstance(values, dict) or all(v is None for v in values.values()):
                    violations.append({'bed_id': bed, 'recv_ms': poll['recv_ms'], 'bed': beds.get(bed)})
    if not checked:
        return row('Never blank violations', 'NOT RUN', reason='No HTTP samples after received telemetry')
    failed_polls = sum('error' in p for p in polls)
    return row('Never blank violations', 'FAIL' if violations else ('NOT RUN' if failed_polls else 'PASS'),
               len(violations), f'{checked} bed samples; {failed_polls} failed HTTP polls', violations)


def blind_time(rows, polls, bed, start, end, gaps):
    if end <= start:
        return {'status': 'NOT RUN', 'reason': 'Episode end missing or before start'}
    baseline = dict(without_s=(end - start + sum(b - a for a, b in gaps)) / 1000,
                    hidden_without_s=(end - start) / 1000,
                    unmonitored_without_s=sum(b - a for a, b in gaps) / 1000)
    alert = first_after(rows, bed, start, nurse, end)
    notified = alert['recv_ms'] if alert else end
    hidden = (notified - start) / 1000
    samples = sorted((p for p in polls if isinstance(p.get('data'), dict)), key=lambda p: p['recv_ms'])
    unmonitored, covered = 0, 0
    for a, b in zip(samples, samples[1:]):
        lo, hi = max(start, a['recv_ms']), min(notified, b['recv_ms'])
        if hi <= lo:
            continue
        found = next((x for x in bed_entries(a) if x.get('bed_id') == bed), None)
        if b['recv_ms'] - a['recv_ms'] > 2500 or found is None:
            return {**baseline, 'status': 'NOT RUN', 'reason': 'Missing bed or gap over 2.5 s in ward polls'}
        covered += hi - lo
        if found.get('display') in ('last_trusted', 'offline'):
            unmonitored += (hi - lo) / 1000
    if covered < notified - start:
        return {**baseline, 'status': 'NOT RUN', 'reason': 'Ward polls do not cover the pre-alert interval'}
    gap_s = sum((b - a) / 1000 for a, b in gaps)
    return dict(status='PASS', with_s=hidden + unmonitored, without_s=(end - start) / 1000 + gap_s,
                hidden_with_s=hidden, unmonitored_with_s=unmonitored,
                hidden_without_s=(end - start) / 1000, unmonitored_without_s=gap_s,
                alert_recv_ms=alert['recv_ms'] if alert else None,
                reason='No staff alert before episode end; hidden time is full episode' if not alert else '')


# bed, target, script second, bound seconds, ground-truth event. Cuffs are read from vitals.
EXPECTATIONS = [
    ('B03', 'EMERGENCY', 300, 15, 'monitor_alarm'),
    ('B04', 'LOOSE_SENSOR', 390, 15, 'monitor_alarm'),
    ('B09', 'EMERGENCY', 516, 30, 'cuff'),
    ('B05', 'TAMPERING', 600, 15, 'attack_start'),
    ('B05', 'NORMAL', 930, 15, 'undo'),
    ('B08', 'DRIFTING', 666, 30, 'cuff'),
    ('B08', 'NORMAL', 972, 30, 'cuff'),
    ('B11', 'DEVICE_ATTACK', 720, 15, 'attack_start'),
    ('B10', 'TAMPERING', 360, 15, 'attack_start'),
    ('B07', 'TAMPERING', 825, 15, 'attack_start'),
    ('B07', 'BOTH', 840, 15, 'monitor_alarm'),
    ('B06', 'TAMPERING', 960, 15, 'attack_start'),
    ('B12', 'UNSURE', 1020, 15, 'attack_start'),
    ('B12', 'NORMAL', 1080, 15, 'bedside'),
]


def origin_ms(events):
    start = next((e for e in events if e.get('event') == 'run_start'), None)
    if start:
        detail = start.get('detail') or {}
        return detail.get('origin_ms', start['ts'] - start.get('t_s', 0) * 1000)
    return None


def anchor(events, attacks, rows, bed, kind, t_s, origin):
    pool = attacks if kind == 'attack_start' else events
    found = [e for e in pool if e.get('event') == kind and e.get('bed_id') == bed]
    if found:
        event = min(found, key=lambda e: abs(e.get('t_s', t_s) - t_s))
        return event['ts'], 'event log', [event]
    if kind == 'cuff':
        cuffs = [r for r in observed(rows) if r['message'].get('bed_id') == bed
                 and r['message'].get('type') == 'vitals' and isinstance(r['message'].get('nibp'), dict)
                 and isinstance(r['message']['nibp'].get('ts'), (int, float))]
        cuffs = [r for r in cuffs if abs(r['message']['nibp']['ts'] - (origin + t_s * 1000)) <= 2000]
        if cuffs:
            return cuffs[0]['message']['nibp']['ts'], 'received cuff timestamp', evidence(cuffs[0])
    if kind in ('undo', 'bedside'):
        hit = first_after(rows, bed, origin + (t_s - 5) * 1000,
                          lambda m: (kind == 'undo' and m.get('type') == 'action' and m.get('undoes')
                                     and m.get('result') == 'ok') or
                                    (kind == 'bedside' and m.get('type') == 'bedside_check'
                                     and m.get('result') == 'patient_ok'))
        if hit:
            return hit['message'].get('ts', hit['recv_ms']), 'MQTT event timestamp', evidence(hit)
    return origin + t_s * 1000, 'script time (ground truth unavailable)', []


def verdict_checks(events, attacks, rows):
    origin = origin_ms(events)
    if origin is None:
        return [row(f'{b} {v}', 'NOT RUN', reason='Missing simulator run_start') for b, v, *_ in EXPECTATIONS]
    end = max((e['ts'] for e in events if e.get('event') == 'run_end'), default=origin + 1200000)
    result = []
    for bed, target, t_s, bound, kind in EXPECTATIONS:
        start, source, proof = anchor(events, attacks, rows, bed, kind, t_s, origin)
        hit = first_after(rows, bed, start, lambda m: m.get('type') == 'verdict' and m.get('verdict') == target, end)
        delay = (hit['recv_ms'] - start) / 1000 if hit else None
        note = f'{source}; limit {bound} s; event_ms={start}'
        if bed == 'B10':
            note += '; strict doc-07 onset timing (network signs expected about T+13:00)'
        if bed in ('B04', 'B06'):
            note += '; brain README alarm-preservation override may yield EMERGENCY/BOTH'
        result.append(row(f'{bed} {target}', 'PASS' if delay is not None and delay <= bound else 'FAIL',
                          delay, note, proof + evidence(hit)))
    return result


def unique_messages(rows, kind, key):
    unique = {}
    for r in observed(rows):
        m = r['message']
        if m.get('type') == kind:
            value = m.get(key)
            if value is not None:
                unique.setdefault(value, r)
    return list(unique.values())


def resource_metrics(bus, polls, samples):
    result = []
    delays = [p['elapsed_ms'] for p in polls if p.get('status') == 200]
    for p in (50, 95):
        value = percentile(delays, p)
        result.append(row(f'HTTP ward delay p{p} ms', 'PASS' if value is not None else 'NOT RUN', value,
                          'Successful polls only; failures listed separately'))
    for bed in sorted({r['message'].get('bed_id') for r in observed(bus) if r['message'].get('type') == 'verdict'}):
        values = [r['recv_ms'] - (r['message']['window_start'] + 10000) for r in observed(bus)
                  if r['message'].get('type') == 'verdict' and r['message'].get('bed_id') == bed
                  and isinstance(r['message'].get('window_start'), (int, float))]
        for p in (50, 95):
            value = percentile(values, p)
            result.append(row(f'{bed} verdict delay p{p} ms', 'PASS' if value is not None else 'NOT RUN', value,
                              'window_start + 10 s → receipt; negative delay indicates clock/window mismatch'))
    valid = [s for s in samples if 'cpu_percent' in s]
    for key in ('cpu_percent', 'memory_used_bytes'):
        values = [s[key] for s in valid]
        result.append(row(f'System {key} mean', 'PASS' if values else 'NOT RUN',
                          sum(values) / len(values) if values else None))
    if bus and len(bus) > 1:
        span = (max(r['recv_ms'] for r in bus) - min(r['recv_ms'] for r in bus)) / 1000
        result.append(row('Hub observed messages/s mean', 'PASS' if span > 0 else 'NOT RUN',
                          len(bus) / span if span > 0 else None))
    else:
        result.append(row('Hub observed messages/s mean', 'NOT RUN', reason='No receipt interval'))
    return result


def analyze_t8(events, attacks, bus, polls, source_errors=()):
    results = verdict_checks(events, attacks, bus)
    results.append(never_blank(bus, polls))
    live = observed(bus)
    origin = origin_ms(events)
    complete = any(e.get('event') == 'run_end' and isinstance(e.get('detail'), dict)
                   and e['detail'].get('reason') == 'complete' for e in events)
    results.append(row('Complete real-time 20-minute run', 'PASS' if complete else 'NOT RUN',
                       reason='Simulator run_end.reason must be complete; fast runs cannot establish live timings'))
    fast = any(isinstance(e.get('detail'), dict) and e['detail'].get('fast') for e in events)
    if fast:
        source_errors = [*source_errors, 'Fast/virtual run: live latency cannot be scored']
    for bed in ('B01', 'B02'):
        verdicts = [r for r in live if r['message'].get('bed_id') == bed and r['message'].get('type') == 'verdict']
        bad = [r for r in live if r['message'].get('bed_id') == bed and
               (r['message'].get('type') == 'alert' or
                (r['message'].get('type') == 'verdict' and r['message'].get('verdict') != 'NORMAL'))]
        results.append(row(f'{bed} no false alerts', 'FAIL' if bad else ('PASS' if verdicts and complete else 'NOT RUN'),
                           len(bad), 'Requires full-run verdict coverage', evidence(*bad)))
    for bed in ('B09', 'B10'):
        verdicts = [r for r in live if r['message'].get('type') == 'verdict' and r['message'].get('bed_id') == bed]
        bad = [r for r in verdicts if r['message'].get('verdict') == 'DRIFTING']
        results.append(row(f'{bed} never DRIFTING', 'FAIL' if bad else ('PASS' if verdicts and complete else 'NOT RUN'),
                           len(bad), evidence=evidence(*bad)))
    b11_ran = any(e.get('bed_id') == 'B11' and e.get('event') == 'attack_start' for e in attacks)
    b11 = [r for r in live if r['message'].get('bed_id') == 'B11' and nurse(r['message'])]
    results.append(row('B11 no nurse alert', 'FAIL' if b11 else ('PASS' if complete and b11_ran else 'NOT RUN'),
                       len(b11), evidence=evidence(*b11)))
    actions = [r for r in live if r['message'].get('type') == 'action' and r['message'].get('by') in
               {f'A{i}' for i in range(1, 10)}]
    bad = [r for r in actions if not r['message'].get('undo_id')]
    results.append(row('Automatic actions missing undo_id', 'FAIL' if bad else ('PASS' if actions else 'NOT RUN'),
                       len(bad), 'Strict doc-07 rule applies to every A1–A9 action', evidence(*bad)))
    acked, high_seen, bad_close = set(), False, []
    for r in live:
        m = r['message']
        if m.get('type') == 'action' and m.get('action') == 'record_ack' and m.get('bed_id') == 'B07':
            # Bed-level ack is not assumed to acknowledge every alert; require an explicit alert id.
            if m.get('alert_id'):
                acked.add(m['alert_id'])
        if m.get('type') != 'alert' or m.get('bed_id') != 'B07' or m.get('priority') != 'high':
            continue
        high_seen = True
        if m.get('acked_by') and m.get('acked_ts') is not None and m['acked_ts'] <= r['recv_ms']:
            acked.add(m.get('alert_id'))
        if m.get('status') in ('closed', 'resolved', 'cancelled', 'canceled') and m.get('alert_id') not in acked:
            bad_close.append(r)
    results.append(row('B07 high alert preserved until ack', 'FAIL' if bad_close else
                       ('PASS' if high_seen and complete else 'NOT RUN'), len(bad_close), evidence=evidence(*bad_close)))
    cuts = [r for r in live if r['message'].get('type') == 'action' and r['message'].get('bed_id') == 'B05'
            and r['message'].get('action') == 'disable_client' and r['message'].get('result') == 'ok'
            and r['message'].get('device_id') == 'MON-05']
    attack_start = next((e['ts'] for e in attacks if e.get('bed_id') == 'B05' and e.get('event') == 'attack_start'),
                        origin + 600000 if origin is not None else None)
    tampering = first_after(bus, 'B05', attack_start, lambda m: m.get('type') == 'verdict'
                             and m.get('verdict') == 'TAMPERING') if attack_start is not None else None
    ordered = bool(tampering and cuts and tampering['recv_ms'] <= cuts[0]['recv_ms'])
    results.append(row('B05 verdict before cut-off', 'PASS' if ordered else 'FAIL',
                       (cuts[0]['recv_ms'] - tampering['recv_ms']) / 1000 if ordered else None,
                       'Successful MON-05 cut-off must follow TAMPERING', evidence(tampering, cuts[0] if cuts else None)))
    cut_ids = {r['message'].get('action_id') for r in cuts}
    undo = first_after(bus, 'B05', cuts[0]['recv_ms'] if cuts else float('inf'),
                       lambda m: m.get('type') == 'action' and m.get('undoes') in cut_ids and m.get('result') == 'ok')
    restored = next((p for p in polls if undo and p['recv_ms'] >= undo['recv_ms'] and any(
        b.get('bed_id') == 'B05' and b.get('display') == 'live' for b in bed_entries(p))), None)
    results.append(row('B05 undo restores live display', 'PASS' if restored else 'FAIL',
                       reason='Successful undo must reference the observed cut-off action', evidence=evidence(undo)))
    for bed in ('B05', 'B07'):
        start = next((e['ts'] for e in attacks if e.get('bed_id') == bed and e.get('event') == 'attack_start'), None)
        end = max((e['ts'] for e in events if e.get('event') == 'run_end'), default=None)
        results.append(time_to_safe(bus, bed, start, end) if start is not None and end is not None else
                       row(f'{bed} time-to-safe s', 'NOT RUN', reason='Missing actual attack start or run end'))
    alarms = [e for e in events if e.get('event') == 'monitor_alarm']
    forged = [e for e in attacks if e.get('event') in ('monitor_alarm', 'forged_alarm')]
    nurse_alerts = [r for r in unique_messages(bus, 'alert', 'alert_id') if nurse(r['message'])]
    results.append(row('Nurse alerts sent', 'PASS' if complete else 'NOT RUN', len(nurse_alerts) if complete else None))
    results.append(row('Monitor alarms (simulator only)', 'PASS' if events else 'NOT RUN', len(alarms) if events else None))
    # The current attacker logs starts, not forged alarm occurrences. Observe their original ts/seq on MQTT.
    forged_frames = {}
    flat_start = next((e['ts'] for e in attacks if e.get('bed_id') == 'B06' and e.get('event') == 'attack_start'), None)
    flat_end = next((e['ts'] for e in attacks if e.get('bed_id') == 'B06' and e.get('event') == 'attack_end'), None)
    if not forged and flat_start is not None and flat_end is not None:
        for r in live:
            m = r['message']
            if m.get('type') == 'vitals' and m.get('bed_id') == 'B06' and m.get('monitor_alarm') and flat_start <= r['recv_ms'] <= flat_end:
                forged_frames.setdefault((m.get('seq'), m.get('ts')), r)
    denominator_known = bool(attacks and complete and (forged or forged_frames))
    total_alarms = len(alarms) + len(forged or forged_frames)
    reason = 'Forged alarm occurrences from attack events or B06 alarm frames during logged fake-flatline episode; one occurrence per original seq/ts'
    for name, value in [('Monitor alarms including forged', total_alarms),
                        ('Alarms stopped (count comparison)', total_alarms - len(nurse_alerts))]:
        results.append(row(name, 'PASS' if denominator_known else 'NOT RUN', value if denominator_known else None,
                           reason if denominator_known else 'Missing complete forged-alarm occurrence evidence'))
    blind_rows = []
    for bed in ('B05', 'B06', 'B07', 'B10', 'B12', 'B08'):
        source = events if bed == 'B08' else attacks
        start_kind, end_kind = ('drift_start', 'drift_end') if bed == 'B08' else ('attack_start', 'attack_end')
        start = next((e['ts'] for e in source if e.get('bed_id') == bed and e.get('event') == start_kind), None)
        end = next((e['ts'] for e in source if e.get('bed_id') == bed and e.get('event') == end_kind), None)
        run_end = max((e['ts'] for e in events if e.get('event') == 'run_end'), default=None)
        source_end = next((e['ts'] for e in events if e.get('bed_id') == bed and e.get('event') == 'source_end'), None)
        gaps = [(source_end, run_end)] if source_end is not None and run_end is not None else []
        measurement = blind_time(bus, polls, bed, start, end, gaps) if start is not None and end is not None else {
            'status': 'NOT RUN', 'reason': 'Missing actual episode start/end'}
        blind_rows.append(measurement)
        for suffix, key in [('with SentinelWard s', 'with_s'), ('without SentinelWard s', 'without_s')]:
            status = 'PASS' if key == 'without_s' and key in measurement else measurement['status']
            reason = 'Episode duration + actual recording gap; independent of HTTP coverage' if key == 'without_s' else measurement.get('reason', '')
            results.append(row(f'{bed} Blind Time {suffix}', status, measurement.get(key), reason, [measurement]))
    for label, key in [('with SentinelWard s', 'with_s'), ('without SentinelWard s', 'without_s')]:
        ready = all(key in r and (key == 'without_s' or r['status'] == 'PASS') for r in blind_rows)
        results.append(row(f'Total Blind Time {label}', 'PASS' if ready else 'NOT RUN',
                           sum(r[key] for r in blind_rows) if ready else None, 'Sum of all six affected beds'))
    for label in ('with', 'without'):
        results.append(row(f'B11 hidden time {label} s', 'PASS' if complete and b11_ran else 'NOT RUN', 0 if complete and b11_ran else None,
                           'Definition: network only, no forged readings'))
    detection_rows = []
    for bed in ('B05', 'B06', 'B07', 'B10', 'B11', 'B12'):
        start = next((e['ts'] for e in attacks if e.get('bed_id') == bed and e.get('event') == 'attack_start'), None)
        end = next((e['ts'] for e in attacks if e.get('bed_id') == bed and e.get('event') == 'attack_end'), None)
        targets = {'TAMPERING', 'BOTH'}
        if bed == 'B11':
            targets.add('DEVICE_ATTACK')
        if bed == 'B12':
            targets.add('UNSURE')
        hit = first_after(bus, bed, start, lambda m: m.get('type') == 'verdict' and m.get('verdict') in targets, end) if start is not None and end is not None else None
        ready = start is not None and end is not None
        measurement = row(f'{bed} attack detection delay s', ('PASS' if hit else 'FAIL') if ready else 'NOT RUN',
                          (hit['recv_ms'] - start) / 1000 if hit else None,
                          'Actual attack start → first integrity warning; BOTH counts as caught under alarm preservation; '
                          'B12 UNSURE counts as the prescribed warning', evidence(hit))
        detection_rows.append(measurement)
        results.append(measurement)
    all_attacks_known = complete and all(r['status'] != 'NOT RUN' for r in detection_rows)
    caught = sum(r['value'] is not None for r in detection_rows)
    on_time = sum(r['value'] is not None and r['value'] <= 15 for r in detection_rows)
    for label, value in [('Attacks caught', caught), ('Attacks caught on time', on_time)]:
        results.append(row(label, ('PASS' if value == 6 else 'FAIL') if all_attacks_known else 'NOT RUN',
                           value if all_attacks_known else None, 'Six actual logged attack episodes; on-time means within 15 s'))
    emergency_rows = []
    for bed, t_s, bound, kind in [('B03', 300, 15, 'monitor_alarm'), ('B09', 516, 30, 'cuff'), ('B07', 840, 15, 'monitor_alarm')]:
        if origin is None:
            emergency_rows.append(row(f'{bed} emergency detection delay s', 'NOT RUN', reason='No run origin'))
            continue
        start, source, proof = anchor(events, attacks, bus, bed, kind, t_s, origin)
        end = max((e['ts'] for e in events if e.get('event') == 'run_end'), default=start + bound * 1000)
        hit = first_after(bus, bed, start, lambda m: m.get('type') == 'verdict' and m.get('verdict') in ('EMERGENCY', 'BOTH'), end)
        delay = (hit['recv_ms'] - start) / 1000 if hit else None
        emergency_rows.append(row(f'{bed} emergency detection delay s', 'PASS' if delay is not None and delay <= bound else 'FAIL',
                                  delay, source + f'; EMERGENCY or BOTH preserves the emergency; deadline {bound} s', proof + evidence(hit)))
    results.extend(emergency_rows)
    emergency_ready = complete and bool(live) and len(emergency_rows) == 3
    missed = sum(r['status'] != 'PASS' for r in emergency_rows)
    results.append(row('Missed emergencies by deadline', ('FAIL' if missed else 'PASS') if emergency_ready else 'NOT RUN',
                       missed if emergency_ready else None,
                       'Three real emergencies; no EMERGENCY/BOTH by the deadline counts as missed, including late detection'))
    bus_bad = any('bus.jsonl' in e or 'capture disconnected' in e for e in source_errors)
    polls_bad = any('ward_polls.jsonl' in e for e in source_errors)
    events_bad = any('simulator_events.jsonl' in e for e in source_errors)
    attacks_bad = any('attacks_events.jsonl' in e or 'Missing attacks' in e for e in source_errors)
    for r in results:
        name = r['name']
        uncertain = (bus_bad and name != 'Complete real-time 20-minute run' and name != 'Monitor alarms (simulator only)')
        uncertain |= polls_bad and ('Blind Time with SentinelWard' in name or name == 'Never blank violations')
        uncertain |= events_bad and ('Blind Time without' in name or 'Monitor alarms' in name or 'Alarms stopped' in name)
        uncertain |= attacks_bad and ('Monitor alarms including' in name or 'Alarms stopped' in name)
        if uncertain and r['status'] != 'NOT RUN':
            # Preserve observed safety failures, but do not claim a complete aggregate/first-arrival measurement.
            known_violation = r['status'] == 'FAIL' and bool(r['evidence']) and any(
                term in name for term in ('never', 'no false', 'no nurse', 'missing undo', 'preserved until ack'))
            if not known_violation:
                r.update(status='NOT RUN', value=None, reason=r['reason'] + '; required source incomplete')
    for error in source_errors:
        results.append(row('Source completeness', 'NOT RUN', reason=error))
    # Fast/partial runs cannot establish live performance or full-run absence claims.
    if fast or not complete:
        for r in results:
            if r['status'] == 'PASS' or origin is None or (r['status'] == 'FAIL' and not r['evidence']):
                r.update(status='NOT RUN', value=None, reason=r['reason'] + '; incomplete source/run evidence')
    return results
