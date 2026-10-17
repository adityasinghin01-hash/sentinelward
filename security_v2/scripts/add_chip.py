#!/usr/bin/env python3
"""Root: add the AI-chip hub account (sub ward/bed/+/vitals, pub ward/chip/+) and the backend's
ward/chip/+ subscription to the running, locked-down hub. --remove undoes it. Never echoes secrets."""
import argparse
import os
import pwd
from pathlib import Path
import _bootstrap
from sw_sec.chip_account import apply
from sw_sec.deploy import STATE, deployment_lock

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--server-ip',required=True,help='hub address the remote chip client connects to (TLS 8883)')
    p.add_argument('--remote-ca',default='ca.crt',help='CA path as seen by the remote chip client')
    p.add_argument('--service-user',default='linux1')
    p.add_argument('--state',default=str(STATE))
    p.add_argument('--remove',action='store_true')
    a=p.parse_args()
    if os.geteuid()!=0: p.error('Run as root on the server')
    user=pwd.getpwnam(a.service_user)
    os.umask(0o077)
    try:
        with deployment_lock(Path(a.state),blocking=True):
            done=apply(a.state,Path(user.pw_dir)/'sw/security-v2',server_ip=a.server_ip,remote_ca=a.remote_ca,
                       remove=a.remove,owner=user)
        print(('Removed' if a.remove else 'Applied')+' chip hub policy: '+(', '.join(done) or 'no change needed')+
              '. Live roles read back equal to policy. Run verify.py.')
    except Exception as exc:
        print('CHIP ACCOUNT FAILED ('+type(exc).__name__+'); diagnostics withheld. It is idempotent: rerun it, or run it with --remove.')
        raise SystemExit(1) from None
