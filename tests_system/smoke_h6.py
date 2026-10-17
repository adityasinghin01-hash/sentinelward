#!/usr/bin/env python3
"""H6 smoke check. Run with ~/sw/.venv/bin/python tests_system/smoke_h6.py."""
from __future__ import annotations
if __package__ in (None, ''):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import argparse
import json
from pathlib import Path
import statistics
import subprocess
import time
from tests_system.metrics import (read_jsonl, observed, row, first_after, nurse, evidence,
                                   never_blank, latest, verdict_value, percentile, origin_ms, bed_entries)
from tests_system.reporting import write_report
from tests_system.runtime import (ROOT, OUT, RESULTS, Capture, Api, Poller, WebSocketCapture,
                                  add_arguments, Unavailable, identifier, sim_command, stop_child, safe_error)

OWNER = 'Aditya Singh'


def analyze(bus, polls, ws, events, errors=()):
    rows = []
    live = observed(bus)
    vitals = [r for r in live if r['message'].get('type') == 'vitals' and r['message'].get('bed_id') == 'B03']
    # Contract: start 270, source_end 330. A 75-second watch has 60 source frames, not 75.
    seq = [r['message'].get('seq') for r in vitals]
    valid = not any(r.get('errors') for r in bus if r.get('topic') == 'ward/bed/B03/vitals')
    contiguous = all(isinstance(a, int) and isinstance(b, int) and b == a + 1 for a, b in zip(seq, seq[1:]))
    count_ok = 58 <= len(vitals) <= 62
    size = statistics.median(r['size_bytes'] for r in vitals) if vitals else None
    rows.append(row('Vitals count, sequence, validation', 'PASS' if vitals and valid and contiguous and count_ok else 'FAIL',
                    len(vitals), f'Expected 60 ±2: B03 source stops at T+05:30; continuous={contiguous}, valid={valid}; '
                    f'median wire bytes={size}; nominal about 3 KB (waveform dependent)', owner=OWNER))
    origin = origin_ms(events)
    alarm = next((r for r in vitals if (r['message'].get('monitor_alarm') or {}).get('code') == 'VTACH'), None)
    alarm_event = next((e for e in events if e.get('event') == 'monitor_alarm' and e.get('bed_id') == 'B03'), None)
    start = alarm_event['ts'] if alarm_event else (alarm['message']['ts'] if alarm else None)
    offset = (alarm['message']['ts'] - origin) / 1000 if alarm and origin is not None else None
    rows.append(row('VTACH at T+05:00 ±1 s', 'PASS' if offset is not None and abs(offset - 300) <= 1 else 'FAIL',
                    offset, 'Simulator event origin and vitals timestamp', evidence(alarm), OWNER))
    for model, owner in [(f'M{i}', 'Aditya Singhal' if i <= 4 else ('Kartik' if i == 5 else 'Aditya')) for i in range(1, 7)]:
        scores = [r for r in live if r['message'].get('type') == 'score' and r['message'].get('bed_id') == 'B03'
                  and r['message'].get('model') == model and isinstance(r['message'].get('window_start'), (int, float))]
        delays = [r['recv_ms'] - (r['message']['window_start'] + r['message'].get('window_s', 10) * 1000) for r in scores]
        rows.append(row(f'Scores {model} window-end delay median ms', 'PASS' if scores else 'MISSING',
                        percentile(delays, 50), f'{len(scores)} envelopes; delays_ms={delays}; '
                        'null/ineligible scores are envelopes, not proof of detector readiness', owner=owner))
    verdict = first_after(bus, 'B03', start, lambda m: m.get('type') == 'verdict' and m.get('verdict') == 'EMERGENCY') if start else None
    alert = first_after(bus, 'B03', start, lambda m: nurse(m) and m.get('priority') == 'high') if start else None
    for name, hit, owner in [('EMERGENCY within 15 s', verdict, 'Aditya Singhal'), ('High staff alert within 15 s', alert, 'Aditya')]:
        delay = (hit['recv_ms'] - start) / 1000 if hit else None
        rows.append(row(name, 'PASS' if delay is not None and delay <= 15 else ('FAIL' if hit else 'MISSING'), delay,
                        'Seconds after actual monitor alarm', evidence(hit), owner))
    emergency_polls = [(p, b) for p in polls for b in bed_entries(p)
                       if b.get('bed_id') == 'B03' and verdict_value(b) == 'EMERGENCY'
                       and start is not None and p['recv_ms'] >= start]
    rows.append(row('Backend /api/ward EMERGENCY', 'PASS' if emergency_polls else ('NOT RUN' if verdict is None else 'FAIL'),
                    (emergency_polls[0][0]['recv_ms'] - start) / 1000 if emergency_polls else None,
                    'Depends on decision-layer EMERGENCY; saved ward_polls.jsonl', owner=OWNER))
    # WS supports both locked raw messages and the current bed.updated projection.
    pushes = []
    for r in ws:
        m = r.get('message') or {}
        b = m.get('payload', m)
        if isinstance(b, dict) and b.get('bed_id') == 'B03' and verdict_value(b) == 'EMERGENCY' and start is not None and r['recv_ms'] >= start:
            pushes.append(r)
    push = pushes[0] if pushes else None
    rows.append(row('WS EMERGENCY push delay after hub ms', 'PASS' if push and verdict else ('NOT RUN' if verdict is None else 'FAIL'),
                    push['recv_ms'] - verdict['recv_ms'] if push and verdict else None,
                    'WS/MQTT callback ordering can yield a small negative receipt difference; raw timestamps retained',
                    evidence(push), OWNER))
    # Verify backend transport even if other owners have not shipped inference.
    data_polls = [p for p in polls if any(b.get('bed_id') == 'B03' and latest(b) is not None for b in bed_entries(p))]
    data_ws = [r for r in ws if isinstance((r.get('message') or {}).get('payload'), dict)
               and r['message']['payload'].get('bed_id') == 'B03' and latest(r['message']['payload']) is not None]
    rows.append(row('Backend telemetry HTTP + WS', 'PASS' if data_polls and data_ws else 'FAIL',
                    reason=f'HTTP telemetry polls={len(data_polls)}, WS telemetry pushes={len(data_ws)}', owner=OWNER))
    blank = never_blank(bus, polls)
    blank['owner'] = OWNER
    rows.append(blank)
    rows.append(row('Phone Telegram delivery', 'NOT RUN', reason='A person must verify actual Telegram delivery', owner='Aditya'))
    if errors and (not bus or not events):
        for r in rows:
            if r['status'] in ('PASS', 'FAIL', 'MISSING'):
                r.update(status='NOT RUN', value=None, reason='Required raw inputs unavailable; ' + '; '.join(errors))
    for error in errors:
        rows.append(row('Source/runner', 'NOT RUN', reason=error, owner=OWNER))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_arguments(parser)
    parser.add_argument('--analyze', type=Path, help='Recompute a saved smoke folder offline')
    args = parser.parse_args()
    directory = args.analyze or OUT / identifier('smoke')
    if not args.analyze:
        directory.mkdir(parents=True, exist_ok=False)
    errors, child, api, capture, polls, ws = [], None, None, None, None, None
    if not args.analyze:
        try:
            capture = Capture(directory)
            if not capture.quiet():
                raise Unavailable('Existing ward vitals observed; smoke requires an idle ward')
            api = Api(args.api, args.users)
            polls, ws = Poller(api, directory), WebSocketCapture(api, directory)
            # A unique client id avoids disconnecting the existing listen-mode simulator.
            import yaml
            script = yaml.safe_load((ROOT / 'simulator' / 'ward_script.yaml').read_text())
            script['mqtt_client_id'] = identifier('smoke-sim')
            script_path = directory / 'ward_script.yaml'
            script_path.write_text(yaml.safe_dump(script))
            command = sim_command(args, 'run', '--beds', 'B03', '--start-at', 'T+04:30',
                                  '--run-id', directory.name, '--runs', str(directory / 'runs'))
            command[command.index('--script') + 1] = str(script_path)
            with (directory / 'simulator.log').open('x') as output:
                child = subprocess.Popen(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
                deadline = time.monotonic() + 75
                while time.monotonic() < deadline:
                    if child.poll() is not None:
                        errors.append(f'Simulator exited early: {child.returncode}')
                        break
                    time.sleep(.25)
                stop_child(child)
        except KeyboardInterrupt:
            errors.append('Interrupted; stopped only the simulator child started by this test')
        except Exception as exc:
            errors.append('Runner: ' + safe_error(exc))
        finally:
            stop_child(child)
            for service in (ws, polls, capture, api):
                if service:
                    service.close()
        (directory / 'runner.json').write_text(json.dumps({'errors': errors}))
    bus, be = read_jsonl(directory / 'bus.jsonl')
    ward, we = read_jsonl(directory / 'ward_polls.jsonl')
    socket_rows, se = read_jsonl(directory / 'ws.jsonl')
    events, ee = read_jsonl(directory / 'runs' / directory.name / 'events.jsonl')
    if (directory / 'runner.json').exists():
        errors = json.loads((directory / 'runner.json').read_text())['errors']
    rows = analyze(bus, ward, socket_rows, events, errors + be + we + se + ee)
    report = write_report(directory, 'H6', rows, {'raw_folder': str(directory)})
    (directory / 'report.md').write_text(report)
    write_report(RESULTS, 'H6', rows, {'raw_folder': str(directory)})
    for r in rows:
        print(f"{r['status']:7} {r['name']}: {r['value'] if r['value'] is not None else '—'}; {r['reason']} [{r['owner']}]")
    print(directory)
    return int(any(r['status'] != 'PASS' for r in rows if r['owner'] == OWNER))


if __name__ == '__main__':
    raise SystemExit(main())
