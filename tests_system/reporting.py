"""Shared JSON, CSV and Markdown output; no unmeasured numeric placeholders."""
import csv
import json
from pathlib import Path
from .metrics import DEFINITIONS, row


def number(value):
    return f'{value:.3f}'.rstrip('0').rstrip('.') if isinstance(value, float) else str(value)


def cell(value):
    return str(value).replace('|', '\\|').replace('\n', ' ')


def write_report(directory, name, rows, metadata=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    payload = dict(test=name, metadata=metadata or {}, definitions=DEFINITIONS, rows=rows)
    (directory / f'{name}_results.json').write_text(json.dumps(payload, indent=2, allow_nan=False) + '\n')
    lines = [f'# {name}', '', *[f'- {x}' for x in DEFINITIONS], '']
    pending = [r for r in rows if r['status'] == 'NOT RUN']
    if pending:
        lines += ['Missing checks: ' + '; '.join(f"{r['name']}: {r['reason']}" for r in pending), '']
    lines += ['| Check | Status | Value | Owner | Reason |', '|---|---|---:|---|---|']
    for r in rows:
        lines.append('| ' + ' | '.join(cell(x) for x in (r['name'], r['status'],
                     number(r['value']) if r['value'] is not None else '—', r.get('owner', ''), r['reason'])) + ' |')
    lines += ['', 'Evidence (exact message/event timestamps):', '', '```json',
              json.dumps([{'name': r['name'], 'status': r['status'], 'evidence': r.get('evidence', [])}
                          for r in rows if r.get('evidence')], indent=2), '```', '']
    text = '\n'.join(lines)
    (directory / f'{name}_results.md').write_text(text)
    with (directory / f'{name}_results.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['name', 'status', 'value', 'owner', 'reason'])
        writer.writeheader()
        for r in rows:
            writer.writerow({k: number(r.get(k)) if k == 'value' and r.get(k) is not None else r.get(k, '')
                             for k in writer.fieldnames})
    return text


def summary(reports, expected_runs=3):
    groups = {}
    for report in reports:
        for r in report['rows']:
            groups.setdefault(r['name'], []).append(r if report.get('complete', True) else {**r, 'status': 'NOT RUN', 'value': None})
    result = []
    for name, rows in groups.items():
        values = [r['value'] for r in rows if r['status'] in ('PASS', 'FAIL') and isinstance(r['value'], (int, float))]
        ready = len(values) == expected_runs and len(rows) == expected_runs
        for suffix, fn in [('mean', lambda a: sum(a) / len(a)), ('min', min), ('max', max)]:
            result.append(row(f'{name} {suffix}', 'MEASURED' if ready else 'NOT RUN', fn(values) if ready else None,
                              f'{len(values)}/{expected_runs} numeric runs; FAIL values retained, missing runs never imputed'))
    return result
