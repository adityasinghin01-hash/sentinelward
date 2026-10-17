#!/usr/bin/env python3
"""Read-only root verification: effective listeners/config/ACL and TLS settings."""
import argparse
import json
import os
from pathlib import Path
import re
import _bootstrap
from sw_sec.deploy import BROKER_DIR, SITE, check_admin
from sw_sec.io import private_read, run_checked
from sw_sec.policy import DEVICES, roles
from sw_sec.mqtt_probe import probe

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--service-state',default='/home/linux1/sw/security-v2'); a=p.parse_args()
    if os.geteuid()!=0: p.error('Run as root to inspect broker configuration')
    try:
        root=Path(a.service_state)
        check_admin(root/'admin.conf')
        current=json.loads((BROKER_DIR/'dynamic-security.json').read_text())
        expected={r['rolename']:r['acls'] for r in roles()}
        actual={r['rolename']:r.get('acls',[]) for r in current['roles']}
        # Exact role policy, normalized because Mosquitto can reorder ACLs on save.
        normalize=lambda a:sorted((x['acltype'],x['topic'],x['allow'],x.get('priority',0)) for x in a)
        assert set(expected)==set(actual)
        assert all(normalize(expected[k])==normalize(actual[k]) for k in expected)
        assert current['defaultACLAccess']=={'publishClientSend':False,'publishClientReceive':False,'subscribe':False,'unsubscribe':True}
        assert not current.get('groups') and not current.get('anonymousGroup')
        for device in DEVICES:
            c=next(c for c in current['clients'] if c['username']==device)
            assert c['clientid']==device and c['roles']==[{'rolename':'monitor-'+device[-2:],'priority':0}]
            assert not c.get('groups')
        config=SITE.read_text()
        assert 'listener 1883 127.0.0.1\n' in config and 'allow_anonymous false' in config
        output=run_checked(['ss','-H','-ltn']).stdout
        plain=[line for line in output.splitlines() if re.search(r':1883\s',line)]
        assert plain and all('127.0.0.1:1883' in line for line in plain)
        assert any(re.search(r':8883\s',line) for line in output.splitlines())
        # Do not connect as a monitor: read-only verification must not kick one off.
        env=dict(line.split('=',1) for line in private_read(root/'env/backend.env').splitlines())
        assert probe('127.0.0.1',8883,username=env['MQTT_USER'],password=env['MQTT_PASS'],ca=root/'ca.crt')['connect']==0
        print('PASS: dynsec policy, loopback-only 1883, TLS 8883, and authenticated TLS verified.')
    except Exception:
        print('FAIL: verification failed; run rollback.py if demo access is affected. Diagnostics withheld.')
        raise SystemExit(1) from None
