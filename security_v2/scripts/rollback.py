#!/usr/bin/env python3
"""Root-only, broker-independent restore of the original demo configuration."""
import argparse
import os
import _bootstrap
from pathlib import Path
from sw_sec.deploy import STATE, deployment_lock, rollback

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--state',default=str(STATE)); a=p.parse_args()
    if os.geteuid()!=0: p.error('Run as root on the server')
    try:
        with deployment_lock(Path(a.state),blocking=True): rollback(Path(a.state))
        print('Original hub configuration and service overrides restored.')
    except Exception:
        print('ROLLBACK FAILED: inspect private server state; original snapshot is retained.')
        raise SystemExit(1) from None
