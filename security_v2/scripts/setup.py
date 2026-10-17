#!/usr/bin/env python3
"""Run as root, between demos, from the deployed checkout."""
import argparse
import os
import _bootstrap
from sw_sec.deploy import STATE, setup

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--server-ip',required=True)
    p.add_argument('--service-user',default='linux1')
    p.add_argument('--state',default=str(STATE))
    p.add_argument('--plugin',default='/usr/lib/s390x-linux-gnu/mosquitto_dynamic_security.so')
    p.add_argument('--app',default='/home/linux1/sw/app')
    p.add_argument('--venv',default='/home/linux1/sw/.venv')
    p.add_argument('--log-path',default='/var/log/mosquitto/mosquitto.log')
    args=vars(p.parse_args())
    os.umask(0o077)
    try: setup(**args)
    except (Exception,KeyboardInterrupt):
        print('SETUP FAILED: diagnostics withheld. Run rollback.py if services have not recovered.')
        raise SystemExit(1) from None
