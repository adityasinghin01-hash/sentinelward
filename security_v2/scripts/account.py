#!/usr/bin/env python3
"""Create/update one existing backend identity with a real password, never echoed."""
import argparse
import getpass
import json
from pathlib import Path
import _bootstrap
from sw_sec.io import private_read, private_write
from sw_api.auth import hash_password
from sw_api.config import Settings, load_users

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('username'); p.add_argument('--file',type=Path,required=True)
    a=p.parse_args()
    users=load_users(Settings.from_env().users_yaml)
    if a.username not in users: p.error('Username must already exist in backend users.yaml')
    password=getpass.getpass('New account password: ')
    confirm=getpass.getpass('Repeat password: ')
    if password!=confirm or len(password)<12: p.error('Matching passwords of at least 12 characters required')
    try:
        accounts=json.loads(private_read(a.file)) if a.file.exists() else {}
        accounts[a.username]=hash_password(password)
        private_write(a.file,json.dumps(accounts,indent=2)+'\n')
        print('Private account hash saved. Restart sw-api to load it; plaintext was not written.')
    except Exception:
        print('Account provisioning failed; diagnostics withheld.')
        raise SystemExit(1) from None
