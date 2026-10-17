#!/usr/bin/env python3
import argparse
import os
from pathlib import Path
import _bootstrap
from sw_sec.live import run_live

if __name__=='__main__':
    p=argparse.ArgumentParser(description='Maintenance-window security probes; stop simulator and attacks first.')
    p.add_argument('--service-state',default=str(Path.home()/'sw/security-v2'))
    p.add_argument('--evidence',default=str(Path(__file__).resolve().parents[1]/'evidence'))
    p.add_argument('--host',default='127.0.0.1'); p.add_argument('--tls-host',default='127.0.0.1')
    a=p.parse_args()
    if os.environ.get('SW_SECURITY_LIVE')!='1':
        p.error('Live tests are gated: set SW_SECURITY_LIVE=1 in a maintenance window')
    try: good=run_live(a.service_state,a.evidence,host=a.host,tls_host=a.tls_host)
    except Exception:
        print('FAIL: live test prerequisites missing; diagnostics withheld')
        raise SystemExit(1) from None
    raise SystemExit(0 if good else 1)
