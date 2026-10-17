#!/usr/bin/env python3
"""Run the full real-time ward three times, or recompute a raw output folder."""
from __future__ import annotations
if __package__ in (None, ''):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import argparse
import json
from pathlib import Path
import shutil
import time
from tests_system.metrics import read_jsonl, analyze_t8, row, origin_ms
from tests_system.runtime import (OUT, RESULTS, Capture, Api, Poller, identifier, safe_error,
                                  add_arguments, Unavailable, events_for, safe_run_id)
from tests_system.reporting import write_report


def run_once(args, measure_resources):
    directory = OUT / identifier('t8')
    directory.mkdir(parents=True, exist_ok=False)
    errors, run_id, capture, api, poller, sampler = [], None, None, None, None, None
    sim_path = attack_path = None
    completed = False
    try:
        capture = Capture(directory)
        if not capture.quiet():
            raise Unavailable('Existing ward is active; refusing to replace it')
        api = Api(args.api, args.users)
        health = api.get('/api/health')
        health.raise_for_status()
        if not health.json().get('mqtt_connected'):
            raise Unavailable('Backend MQTT unavailable')
        poller = Poller(api, directory)
        if measure_resources:
            try:
                from tests_system.t10_resources import ResourceSampler
                sampler = ResourceSampler(directory)
            except Exception as exc:
                errors.append('Resource sampler: ' + safe_error(exc))
        receipt = api.post('/api/demo/run', {'start_at_s': 0, 'scenario': 'full_ward_script', 'speed': 1})
        run_id = safe_run_id(receipt['run_id'])
        sim_path, attack_path = events_for(args.sim_runs, run_id), events_for(args.attack_runs, run_id)
        deadline = time.monotonic() + 1245
        saw_start = False
        while time.monotonic() < deadline:
            events, _ = read_jsonl(sim_path)
            saw_start |= any(e.get('event') == 'run_start' for e in events)
            if sampler:
                sampler.origin_ms = origin_ms(events)
            ending = next((e for e in events if e.get('event') in ('run_end', 'run_reset')), None)
            if ending:
                completed = ending['event'] == 'run_end' and ending.get('detail', {}).get('reason') == 'complete'
                if not completed:
                    errors.append('Simulator ended early or reset; see events')
                until = time.monotonic() + 30
                while time.monotonic() < until:
                    time.sleep(.25)
                break
            if not saw_start and time.monotonic() > deadline - 1230:
                errors.append('No simulator run_start within 15 s; check sw-sim and packs')
                break
            time.sleep(.5)
        else:
            errors.append('No simulator run_end before 1245 s deadline')
    except KeyboardInterrupt:
        errors.append('Interrupted')
    except Exception as exc:
        errors.append('Runner: ' + safe_error(exc))
    finally:
        # Reset only if the most recent observed run control still belongs to this test.
        if api and run_id and not completed and capture:
            controls = [r['message'] for r in capture.snapshot() if isinstance(r.get('message'), dict)
                        and r['message'].get('type') == 'demo_control' and r['message'].get('cmd') == 'run']
            if controls and controls[-1].get('run_id') == run_id:
                try:
                    api.post('/api/demo/reset', {})
                    time.sleep(1)
                except Exception as exc:
                    errors.append('Own-run reset failed: ' + safe_error(exc))
        for service in (sampler, poller, capture, api):
            if service:
                service.close()
        for label, path in [('simulator', sim_path), ('attacks', attack_path)]:
            if path and path.exists():
                shutil.copyfile(path, directory / f'{label}_events.jsonl')
            else:
                errors.append(f'Missing {label} events.jsonl')
        (directory / 'run.json').write_text(json.dumps(dict(run_id=run_id, errors=errors, completed=completed), indent=2))
    if run_id:
        final_directory = OUT / ('t8_' + run_id)
        if final_directory != directory and not final_directory.exists():
            directory.rename(final_directory)
            directory = final_directory
    return directory


def analyze(directory):
    directory = Path(directory)
    inputs, errors = [], []
    for name in ('simulator_events.jsonl', 'attacks_events.jsonl', 'bus.jsonl', 'ward_polls.jsonl'):
        rows, problems = read_jsonl(directory / name)
        inputs.append(rows)
        errors += problems
    if (directory / 'run.json').exists():
        errors += json.loads((directory / 'run.json').read_text()).get('errors', [])
    if (directory / 'capture.json').exists():
        state = json.loads((directory / 'capture.json').read_text())
        stats = state.get('stats', {})
        if stats.get('reconnects') or not state.get('connected_at_end', False):
            errors.append('MQTT capture disconnected/reconnected: absence and aggregate counts are incomplete')
    rows = analyze_t8(*inputs, source_errors=errors)
    if any('capture disconnected' in e for e in errors):
        for r in rows:
            if r['status'] == 'PASS' and any(term in r['name'] for term in ('never', 'no false', 'no nurse', 'Nurse alerts', 'Alarms', 'alarms', 'Blind Time', 'Missed emergencies')):
                r.update(status='NOT RUN', value=None, reason=r['reason'] + '; MQTT capture gap')
    write_report(directory, 'T8', rows, {'raw_folder': str(directory)})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_arguments(parser)
    parser.add_argument('--runs', type=int, default=3, choices=(1, 2, 3))
    parser.add_argument('--analyze', type=Path, action='append', help='Saved raw folder, repeat for multiple runs')
    args = parser.parse_args()
    directories = args.analyze or []
    if not args.analyze:
        for n in range(args.runs):
            directory = run_once(args, measure_resources=n == 0)
            directories.append(directory)
            analyze(directory)
            print(f'Run {n + 1} saved: {directory}', flush=True)
            state = json.loads((directory / 'run.json').read_text())
            if not state['completed']:
                break  # Do not repeat a failed setup or interrupted run.
    from tests_system.results_table import generate
    rows = generate(directories)
    if directories and (directories[0] / 'resources.jsonl').exists():
        from tests_system.t10_resources import analyze as analyze_resources
        write_report(RESULTS, 'T10', analyze_resources(directories[0]), {'raw_folder': str(directories[0])})
    return int(any(r['status'] in ('FAIL', 'NOT RUN') for r in rows))


if __name__ == '__main__':
    raise SystemExit(main())
