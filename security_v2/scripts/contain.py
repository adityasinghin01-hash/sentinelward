#!/usr/bin/env python3
"""Device-only containment. No sudo required with the private admin option file."""
import argparse
import json
import os
import _bootstrap
from sw_sec.containment import Containment


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation',choices=['disable_client','enable_client','list'])
    p.add_argument('device',nargs='?')
    p.add_argument('--options',default=os.environ.get('SW_DYNSEC_OPTIONS'))
    p.add_argument('--audit',default=os.environ.get('SW_CONTAIN_AUDIT'))
    p.add_argument('--dry-run',action='store_true')
    a=p.parse_args()
    if not a.options or not a.audit: p.error('Set --options and --audit or their documented environment variables')
    h=Containment(a.options,a.audit)
    try:
        if a.operation=='list':
            print(json.dumps(h.list(),sort_keys=True))
        else:
            if not a.device: p.error('device is required')
            getattr(h,a.operation)(a.device,dry_run=a.dry_run)
            print('DRY RUN' if a.dry_run else 'CONFIRMED')
    except (ValueError,RuntimeError,OSError):
        print('FAILED: check private configuration and broker state; diagnostics withheld')
        return 1
    return 0

if __name__=='__main__': raise SystemExit(main())
