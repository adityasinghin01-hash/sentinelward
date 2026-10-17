#!/usr/bin/env python3
"""Rebuild per-run T8 tables and the three-run mean/min/max without network access."""
if __package__ in (None, ''):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import argparse
from pathlib import Path
from tests_system.reporting import write_report, summary
from tests_system.runtime import RESULTS
from tests_system.metrics import row


def generate(directories):
    from tests_system.t8_ward import analyze
    reports, all_rows = [], []
    for n, directory in enumerate(directories, 1):
        rows = analyze(directory)
        complete = any(r['name'] == 'Complete real-time 20-minute run' and r['status'] == 'PASS' for r in rows)
        reports.append({'rows': rows, 'complete': complete})
        all_rows.extend({**r, 'name': f'Run {n}: {r["name"]}'} for r in rows)
    all_rows += summary(reports, expected_runs=3)
    complete_count = sum(r['complete'] for r in reports)
    all_rows.append(row('Three full ward runs available', 'PASS' if complete_count == 3 and len(reports) == 3 else 'NOT RUN',
                        complete_count, 'Three independent complete runs are required; see run completeness rows'))
    write_report(RESULTS, 'T8', all_rows, {'raw_folders': [str(d) for d in directories]})
    for r in all_rows:
        if ' mean' in r['name'] or r['status'] in ('FAIL', 'NOT RUN'):
            print(f"{r['status']}: {r['name']} = {r['value']}; {r['reason']}")
    print(RESULTS / 'T8_results.md')
    return all_rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folders', type=Path, nargs='+')
    rows = generate(parser.parse_args().folders)
    return int(any(r['status'] in ('FAIL', 'NOT RUN') for r in rows))


if __name__ == '__main__':
    raise SystemExit(main())
