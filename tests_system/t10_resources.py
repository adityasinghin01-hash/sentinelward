#!/usr/bin/env python3
"""T10: resource capture, replay analysis and a guarded 50/100/200/500-bed scale test."""
from __future__ import annotations
if __package__ in (None, ''):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import argparse
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from tests_system.runtime import (ROOT, OUT, RESULTS, JsonLog, Capture, Api, Poller, identifier,
                                  now_ms, Unavailable, safe_error, add_arguments, sim_command, stop_child)
from tests_system.metrics import read_jsonl, resource_metrics, row, percentile, observed
from tests_system.reporting import write_report


def process_role(command, name):
    text = ' '.join(command)
    if name == 'mosquitto':
        return 'mosquitto'
    if name.startswith('postgres'):
        return 'postgres'
    if 'sw_api' in text or 'sw-api' in text or 'uvicorn' in text:
        return 'backend'
    if 'sw_sim' in text or 'sw-sim' in text:
        return 'simulator'
    if 'sw_brain' in text or 'sw-brain' in text:
        return 'brain (M1–M6)'
    if 'sw_attacks' in text or 'sw-attacks' in text:
        return 'attacks'
    if any(x in text for x in ('sw_agents', 'sw-agents', 'security_v2/', 'sw_sec', 'extractor', 'model_service')):
        return 'agent/model/network'
    return None


class ResourceSampler:
    def __init__(self, directory):
        import psutil
        self.psutil = psutil
        self.directory = Path(directory)
        self.log = JsonLog(self.directory / 'resources.jsonl')
        self.stop_event = threading.Event()
        self.cache = {}
        self.origin_ms = None
        self.top_taken = False
        psutil.cpu_percent(None)
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        deadline = time.monotonic() + 5
        while not self.stop_event.wait(max(0, deadline - time.monotonic())):
            deadline += 5
            processes, found, errors = [], set(), []
            ps = self.psutil
            try:
                for info in ps.process_iter(['pid', 'name', 'cmdline', 'create_time']):
                    try:
                        role = process_role(info.info['cmdline'] or [], info.info['name'] or '')
                        if not role:
                            continue
                        found.add(role)
                        key = (info.pid, info.info['create_time'])
                        process = self.cache.get(key)
                        warm = process is not None
                        if process is None:
                            process = ps.Process(info.pid)
                            self.cache[key] = process
                        cpu = process.cpu_percent(None)
                        processes.append(dict(pid=info.pid, role=role, executable=info.info['name'],
                                              cpu_percent=cpu if warm else None, rss_bytes=process.memory_info().rss,
                                              cpu_note='one-core percent; first observation is warmup' if not warm else 'one-core percent'))
                    except (ps.NoSuchProcess, ps.AccessDenied) as exc:
                        errors.append(safe_error(exc))
                data = dict(recv_ms=now_ms(), cpu_percent=ps.cpu_percent(None),
                            memory_used_bytes=ps.virtual_memory().used, memory_total_bytes=ps.virtual_memory().total,
                            processes=processes, roles_found=sorted(found), errors=errors)
                self.log.write(data)
                if self.origin_ms is not None and now_ms() >= self.origin_ms + 600000 and not self.top_taken:
                    try:
                        with (self.directory / 'top_Tplus1000.txt').open('x') as output:
                            result = subprocess.run(['top', '-b', '-n', '1'], stdout=output, stderr=subprocess.STDOUT, timeout=10,
                                                    env={**os.environ, 'COLUMNS': '160'})
                        self.log.write(dict(recv_ms=now_ms(), top_snapshot='top_Tplus1000.txt', returncode=result.returncode,
                                            script_t_s=(now_ms() - self.origin_ms) / 1000))
                    except Exception as exc:
                        self.log.write(dict(recv_ms=now_ms(), top_error=safe_error(exc)))
                    self.top_taken = True
            except Exception as exc:
                self.log.write(dict(recv_ms=now_ms(), error=safe_error(exc)))

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=15)
        self.log.close()


def analyze(directory):
    bus, be = read_jsonl(Path(directory) / 'bus.jsonl')
    polls, pe = read_jsonl(Path(directory) / 'ward_polls.jsonl')
    samples, se = read_jsonl(Path(directory) / 'resources.jsonl')
    rows = resource_metrics(bus, polls, samples)
    for role in ('mosquitto', 'postgres', 'backend', 'simulator', 'brain (M1–M6)', 'attacks', 'agent/model/network'):
        matches = [p for s in samples for p in s.get('processes', []) if p['role'] == role]
        for key in ('cpu_percent', 'rss_bytes'):
            values = [p[key] for p in matches if p.get(key) is not None]
            rows.append(row(f'{role} {key} mean (per process sample)', 'PASS' if values else 'NOT RUN',
                            sum(values) / len(values) if values else None,
                            f"PIDs={sorted({p['pid'] for p in matches})}; raw per-PID samples in resources.jsonl"))
    rows.append(row('top at T+10:00', 'PASS' if (Path(directory) / 'top_Tplus1000.txt').exists() else 'NOT RUN',
                    reason='Snapshot timing is recorded in resources.jsonl; requires a full T8 run'))
    seconds = {}
    for r in bus:
        seconds[r['recv_ms'] // 1000] = seconds.get(r['recv_ms'] // 1000, 0) + 1
    if seconds:
        seconds = {second: seconds.get(second, 0) for second in range(min(seconds), max(seconds) + 1)}
    if Path(directory).is_dir():
        (Path(directory) / 'hub_per_second.json').write_text(json.dumps(seconds, indent=2))
    for error in be + pe + se:
        rows.append(row('Source completeness', 'NOT RUN', reason=error))
    return rows


def scale(args, destination):
    rows = []
    # Read-only inspection of the simulator's own declared limit; do not manufacture invalid IDs.
    try:
        from sw_sim.scale import MAX_SCALE_BEDS
    except ImportError:
        MAX_SCALE_BEDS = None
    limit_hit = False
    for beds in (50, 100, 200, 500):
        if limit_hit:
            rows.append(row(f'Scale {beds} beds', 'NOT RUN', reason='Stopped after first measured on-time result below 99%'))
            continue
        if MAX_SCALE_BEDS is not None and beds > MAX_SCALE_BEDS:
            rows.append(row(f'Scale {beds} beds', 'NOT RUN', reason=f'Current sw_sim limit {MAX_SCALE_BEDS}; two-digit B13–B99 contract'))
            continue
        directory = destination / identifier(f'scale_{beds}')
        directory.mkdir(parents=True)
        capture = api = poller = sampler = child = None
        try:
            capture = Capture(directory)
            if not capture.quiet():
                rows.append(row(f'Scale {beds} beds', 'NOT RUN', reason='Ward is active; no services were stopped'))
                continue
            api = Api(args.api, args.users)
            response = api.get('/api/health')
            response.raise_for_status()
            if not response.json().get('mqtt_connected'):
                raise Unavailable('Backend MQTT unavailable')
            poller = Poller(api, directory)
            sampler = ResourceSampler(directory)
            command = sim_command(args, 'scale', '--beds', str(beds), '--seconds', '60', '--runs', str(directory / 'runs'))
            with (directory / 'simulator.log').open('x') as output:
                child = subprocess.Popen(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
                child.wait(timeout=90)
            time.sleep(1)
            reports = list((directory / 'runs').glob('*/report.json'))
            if child.returncode != 0 or len(reports) != 1:
                rows.append(row(f'Scale {beds} beds', 'NOT RUN', reason=f'Simulator exit {child.returncode}; report count {len(reports)}; see {directory}'))
                continue
            report = json.loads(reports[0].read_text())
            receipts = [r for r in observed(capture.snapshot()) if r['message'].get('type') == 'vitals'
                        and int(r['message'].get('bed_id', 'B00')[1:]) >= 13]
            unique = {(r['message']['bed_id'], r['message'].get('seq'), r['message'].get('ts')): r for r in receipts}
            receipts = list(unique.values())
            delays = [r['recv_ms'] - r['message']['ts'] for r in receipts]
            expected = beds * 60
            on_time = 100 * sum(0 <= x <= report['lag_budget_ms'] for x in delays) / expected
            state = 'PASS' if on_time >= 99 else 'FAIL'
            rows.append(row(f'Scale {beds} beds on-time %', state, on_time,
                            f'Hub receipts within {report["lag_budget_ms"]} ms of scheduled ts / {expected} offered; missing receipts count late; {directory}',
                            [report]))
            rows.append(row(f'Scale {beds} beds publisher on-time %', 'MEASURED', report['on_time_fraction'] * 100,
                            'Publisher timing is separate from hub receipt timing'))
            for p in (50, 95):
                rows.append(row(f'Scale {beds} beds hub delay p{p} ms', 'MEASURED', percentile(delays, p), 'Scheduled source timestamp → local MQTT receipt'))
            limit_hit = on_time < 99
            if limit_hit:
                rows.append(row('First measured capacity failure beds', 'MEASURED', beds, 'First requested N with hub messages on time below 99%'))
        except KeyboardInterrupt:
            rows.append(row(f'Scale {beds} beds', 'NOT RUN', reason='Interrupted'))
            break
        except Exception as exc:
            rows.append(row(f'Scale {beds} beds', 'NOT RUN', reason=safe_error(exc)))
        finally:
            stop_child(child)
            for service in (sampler, poller, capture, api):
                if service:
                    service.close()
        if (directory / 'resources.jsonl').exists():
            rows += [{**r, 'name': f'Scale {beds}: {r["name"]}'} for r in analyze(directory)
                     if r['name'] != 'top at T+10:00']
    if not limit_hit:
        rows.append(row('Measured capacity limit', 'NOT RUN', reason='No below-99% requested N established; unsupported sizes are not a performance limit'))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_arguments(parser)
    parser.add_argument('--analyze', type=Path, action='append', help='Saved T8/scale folder; repeat to combine')
    parser.add_argument('--scale', action='store_true', help='Run requested scale sizes with ward idle')
    parser.add_argument('--capture-seconds', type=int, default=0, help='Observe an existing T8 run without controlling it')
    args = parser.parse_args()
    rows = []
    directories = args.analyze or []
    if args.capture_seconds:
        directory = OUT / identifier('t10')
        directory.mkdir(parents=True)
        capture = api = poller = sampler = None
        try:
            capture = Capture(directory)
            api = Api(args.api, args.users)
            poller = Poller(api, directory)
            sampler = ResourceSampler(directory)
            until = time.monotonic() + args.capture_seconds
            while time.monotonic() < until:
                time.sleep(.25)
        except (Exception, KeyboardInterrupt) as exc:
            rows.append(row('T10 capture', 'NOT RUN', reason=safe_error(exc)))
        finally:
            for service in (sampler, poller, capture, api):
                if service:
                    service.close()
        directories.append(directory)
    for directory in directories:
        rows += [{**r, 'name': f'{Path(directory).name}: {r["name"]}'} for r in analyze(directory)]
    if args.scale:
        OUT.mkdir(parents=True, exist_ok=True)
        rows += scale(args, OUT)
    if not rows:
        parser.error('Choose --analyze, --scale or --capture-seconds')
    write_report(RESULTS, 'T10', rows, {'raw_folders': [str(d) for d in directories]})
    for r in rows:
        print(f"{r['status']}: {r['name']} = {r['value']}; {r['reason']}")
    print(RESULTS / 'T10_results.md')
    return int(any(r['status'] in ('FAIL', 'NOT RUN') for r in rows))


if __name__ == '__main__':
    raise SystemExit(main())
