"""Transactional server provisioning. Linux/root only; safe offline config generation.

Snapshot and rollback never depend on MQTT credentials or the broker being up.
The external rollback timer survives an interrupted provisioning process.
"""
import base64
from contextlib import contextmanager
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import pwd
import shutil
import time

from .io import private_read, private_write, run_checked
from .containment import ctrl_failed
from .policy import DEVICES, SERVICES, build_config, credentials, service_env

UNITS=('sw-api','sw-brain','sw-sim','sw-attacks','sw-agents','sw-net')
BROKER_DIR=Path('/var/lib/mosquitto/sw-security-v2')
SITE=Path('/etc/mosquitto/conf.d/sentinelward.conf')
STATE=Path('/var/lib/sentinelward-security-v2')
SYSTEMD_DIR=Path('/etc/systemd/system')


class Snapshot:
    def __init__(self,path): self.path=Path(path)

    def capture(self, paths):
        if self.path.exists(): return
        rows=[]
        for item in paths:
            path=Path(item)
            if path.is_symlink(): raise ValueError('Managed paths must not be symlinks')
            if path.exists():
                info=path.stat()
                rows.append({'path':str(path),'data':base64.b64encode(path.read_bytes()).decode(),
                             'mode':info.st_mode & 0o777,'uid':info.st_uid,'gid':info.st_gid})
            else: rows.append({'path':str(path),'data':None})
        private_write(self.path,json.dumps(rows))

    def restore(self):
        for row in json.loads(private_read(self.path)):
            path=Path(row['path'])
            if row['data'] is None:
                if path.exists(): path.unlink()
            else:
                # Managed files are text (systemd/env/Mosquitto); bytes round-trip.
                private_write(path,base64.b64decode(row['data']).decode(),mode=row['mode'])
                if os.geteuid()==0: os.chown(path,row['uid'],row['gid'])


def render_config(plugin, directory):
    directory=Path(directory)
    for value in (str(plugin),str(directory)):
        if any(c.isspace() for c in value): raise ValueError('Broker paths must not contain whitespace')
    return f'''# Fresh SentinelWard security v2, 2026-10-17. Global plugin covers both listeners.
per_listener_settings false
allow_anonymous false
plugin {plugin}
plugin_opt_config_file {directory}/dynamic-security.json
listener 1883 127.0.0.1
listener 8883 0.0.0.0
cafile {directory}/ca.crt
certfile {directory}/server.crt
keyfile {directory}/server.key
tls_version tlsv1.2
require_certificate false
persistence true
autosave_interval 30
max_queued_messages 10000
max_packet_size 1048576
connection_messages true
log_timestamp true
log_type all
'''


@contextmanager
def deployment_lock(state, *, blocking=False):
    state.mkdir(parents=True,exist_ok=True,mode=0o700)
    if state.is_symlink(): raise ValueError('State must not be a symlink')
    os.chmod(state,0o700)
    fd=os.open(state/'lock',os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        yield
    finally: os.close(fd)


def owned_file(path,text,user,mode=0o600):
    private_write(path,text,mode=mode)
    os.chown(path,user.pw_uid,user.pw_gid)


def generate_tls(directory, state, server_ip):
    ipaddress.ip_address(server_ip)
    files=[directory/'ca.crt', directory/'server.crt', directory/'server.key',state/'ca.key']
    if all(path.exists() for path in files):
        run_checked(['openssl','verify','-CAfile',str(directory/'ca.crt'),str(directory/'server.crt')])
        run_checked(['openssl','x509','-in',str(directory/'server.crt'),'-noout','-checkip',server_ip])
        run_checked(['openssl','x509','-in',str(directory/'server.crt'),'-noout','-checkend','86400'])
        return
    if any(path.exists() for path in files):
        raise ValueError('Partial TLS state: inspect private files before retrying; no automatic key rotation')
    # Keep the CA signing key outside the broker's readable directory.
    run_checked(['openssl','req','-x509','-newkey','rsa:3072','-sha256','-nodes','-days','365',
                 '-keyout',str(state/'ca.key'),'-out',str(directory/'ca.crt'),'-subj','/CN=SentinelWard Lab CA',
                 '-addext','basicConstraints=critical,CA:TRUE','-addext','keyUsage=critical,keyCertSign,cRLSign'])
    run_checked(['openssl','req','-new','-newkey','rsa:3072','-nodes','-keyout',str(directory/'server.key'),
                 '-out',str(state/'server.csr'),'-subj','/CN=SentinelWard Hub'])
    private_write(state/'server.ext',f'subjectAltName=IP:{server_ip},IP:127.0.0.1,DNS:localhost\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n')
    run_checked(['openssl','x509','-req','-in',str(state/'server.csr'),'-CA',str(directory/'ca.crt'),
                 '-CAkey',str(state/'ca.key'),'-CAcreateserial','-out',str(directory/'server.crt'),
                 '-days','365','-sha256','-extfile',str(state/'server.ext')])
    os.chmod(state/'ca.key',0o600)


def dropin_path(unit): return SYSTEMD_DIR/(unit+'.service.d')/'90-security-v2.conf'


def unit_exists(unit):
    result=run_checked(['systemctl','show',unit+'.service','--property=LoadState','--value'])
    return result.stdout.strip()=='loaded'


def check_admin(options):
    result=run_checked(['mosquitto_ctrl','-o',str(options),'dynsec','getDefaultACLAccess'])
    if ctrl_failed(result) or 'publishClientReceive' not in result.stdout:
        raise RuntimeError('Dynsec administration check failed')


def rollback(state=STATE):
    state=Path(state)
    if not (state/'backup.json').exists(): raise ValueError('No provisioning snapshot exists')
    status=json.loads(private_read(state/'services.json'))
    # Stop managed producers before restoring the anonymous demo configuration.
    for unit in UNITS:
        if unit_exists(unit): run_checked(['systemctl','stop',unit+'.service'])
    enabled=json.loads(private_read(state/'enabled.json')) if (state/'enabled.json').exists() else {}
    if unit_exists('sw-net') and not enabled.get('sw-net',False):
        run_checked(['systemctl','disable','sw-net.service'])
    Snapshot(state/'backup.json').restore()
    run_checked(['systemctl','daemon-reload'])
    run_checked(['systemctl','restart','mosquitto'])
    for unit,active in status.items():
        if active: run_checked(['systemctl','start',unit+'.service'])
    private_write(state/'status','rolled-back\n')
    # No credentials are needed for the restore; do not delete original backups.


def setup(*, server_ip, service_user='linux1', state=STATE,
          plugin='/usr/lib/s390x-linux-gnu/mosquitto_dynamic_security.so',
          app='/home/linux1/sw/app', venv='/home/linux1/sw/.venv',
          log_path='/var/log/mosquitto/mosquitto.log'):
    if os.geteuid()!=0: raise ValueError('Setup requires root on the server')
    state=Path(state); app=Path(app); venv=Path(venv)
    ipaddress.ip_address(server_ip)
    if not Path(plugin).is_file(): raise ValueError('Dynamic Security plugin not found')
    for exe in ('openssl','mosquitto_ctrl','systemctl','systemd-run'):
        if not shutil.which(exe): raise ValueError('Missing server prerequisite: '+exe)
    user=pwd.getpwnam(service_user); mosquitto=pwd.getpwnam('mosquitto')
    service_state=Path(user.pw_dir)/'sw/security-v2'
    envdir=service_state/'env'
    agent_state=Path(user.pw_dir)/'sw/agents-data'
    admin=service_state/'admin.conf'
    python=venv/'bin/python'
    scripts=app/'security_v2/scripts'
    for value in (app,venv,state,service_state,log_path):
        if any(c.isspace() for c in str(value)): raise ValueError('Deployment paths must not contain whitespace')
    with deployment_lock(state):
        if (state/'status').exists() and (state/'status').read_text().strip()=='active':
            check_admin(admin)
            print('Already active; credentials and containment state preserved. Run verify.py for full checks.')
            return
        if (state/'backup.json').exists() and not (state/'status').exists():
            rollback(state)
        present={unit:unit_exists(unit) for unit in UNITS[:-1]}
        required=('sw-api','sw-brain','sw-sim','sw-attacks')
        if not all(present[u] for u in required):
            raise ValueError('Install the four base stack units before hub setup')
        status={}  # show reports inactive units without an error exit status.
        for unit in UNITS:
            if unit_exists(unit):
                status[unit]=run_checked(['systemctl','show',unit+'.service','--property=ActiveState','--value']).stdout.strip()=='active'
        managed=[SITE,SYSTEMD_DIR/'sw-net.service',*(dropin_path(u) for u in UNITS[:-1])]
        Snapshot(state/'backup.json').capture(managed)
        if not (state/'services.json').exists(): private_write(state/'services.json',json.dumps(status))
        if not (state/'enabled.json').exists():
            enabled=run_checked(['systemctl','show','sw-net.service','--property=UnitFileState','--value']).stdout.strip()=='enabled'
            private_write(state/'enabled.json',json.dumps({'sw-net':enabled}))
        secretfile=state/'credentials.json'
        if secretfile.exists(): values=json.loads(private_read(secretfile))
        else:
            values=credentials()
            private_write(secretfile,json.dumps(values))
        for directory in (service_state,envdir,agent_state):
            directory.mkdir(parents=True,exist_ok=True,mode=0o700)
            os.chmod(directory,0o700); os.chown(directory,user.pw_uid,user.pw_gid)
        BROKER_DIR.mkdir(exist_ok=True,mode=0o750)
        os.chown(BROKER_DIR,mosquitto.pw_uid,mosquitto.pw_gid); os.chmod(BROKER_DIR,0o750)
        generate_tls(BROKER_DIR,state,server_ip)
        for name in ('server.key','server.crt','ca.crt'):
            os.chown(BROKER_DIR/name,mosquitto.pw_uid,mosquitto.pw_gid)
            os.chmod(BROKER_DIR/name,0o600 if name=='server.key' else 0o644)
        owned_file(service_state/'ca.crt',(BROKER_DIR/'ca.crt').read_text(),user,0o644)
        owned_file(service_state/'devices.json',json.dumps({d:values[d] for d in DEVICES}),user)
        owned_file(admin,'-h 127.0.0.1\n-p 8883\n--cafile '+str(service_state/'ca.crt')+'\n-u admin\n-P '+values['admin']+'\n',user)
        for service in SERVICES:
            env=service_env(service,values)
            if service in ('simulator','agents'):
                env['SW_MONITOR_CREDENTIALS']=str(service_state/'devices.json')
            if service=='agents':
                env['SW_DYNSEC_OPTIONS']=str(admin)
                env['SW_CONTAIN_AUDIT']=str(agent_state/'containment.jsonl')
            if service=='extractor': env['SW_MOSQUITTO_LOG']=log_path
            owned_file(envdir/(service+'.env'),''.join(f'{k}={v}\n' for k,v in env.items()),user)
        # Timer is armed BEFORE any broker/service config mutation. It survives
        # SIGKILL/disconnect; normal success cancels it only after verified startup.
        for transient in ('sw-security-v2-rollback.timer','sw-security-v2-rollback.service'):
            loaded=run_checked(['systemctl','show',transient,'--property=LoadState','--value']).stdout.strip()
            if loaded=='loaded': run_checked(['systemctl','stop',transient])
        run_checked(['systemd-run','--unit=sw-security-v2-rollback','--on-active=180s',
                     str(python),str(scripts/'rollback.py'),'--state',str(state)])
        try:
            for unit in UNITS:
                if unit_exists(unit): run_checked(['systemctl','stop',unit+'.service'])
            run_checked(['systemctl','stop','mosquitto'])
            private_write(BROKER_DIR/'dynamic-security.json',json.dumps(build_config(values)))
            os.chown(BROKER_DIR/'dynamic-security.json',mosquitto.pw_uid,mosquitto.pw_gid)
            private_write(SITE,render_config(plugin,BROKER_DIR),mode=0o644)
            for unit,service in [('sw-api','backend'),('sw-brain','brain'),('sw-sim','simulator'),('sw-attacks','attacks'),('sw-agents','agents')]:
                if not present[unit]: continue
                content=f'[Service]\nEnvironmentFile={envdir}/{service}.env\n'
                if unit=='sw-sim':
                    # 2-lead packs (doc 00 v1.3) when built; the 1-lead packs otherwise.
                    packs=Path(user.pw_dir)/'sw'/'packs-v13'
                    if not packs.is_dir(): packs=Path(user.pw_dir)/'sw'/'packs'
                    content+=f'ExecStart=\nExecStart={python} {scripts}/run_simulator.py listen --packs {packs} --runs {user.pw_dir}/sw/runs/simulator --script {app}/simulator/ward_script.yaml\n'
                if unit=='sw-agents':
                    content+=f'WorkingDirectory={agent_state}\nExecStart=\nExecStart={python} {scripts}/run_agents.py\n'
                private_write(dropin_path(unit),content,mode=0o644)
            net=f'''[Unit]
Description=SentinelWard receive and broker-log network features
After=mosquitto.service
Requires=mosquitto.service
[Service]
User={service_user}
Group={user.pw_name}
SupplementaryGroups=adm
EnvironmentFile={envdir}/extractor.env
WorkingDirectory={app}
ExecStart={python} {scripts}/extractor.py
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=true
UMask=0077
[Install]
WantedBy=multi-user.target
'''
            private_write(SYSTEMD_DIR/'sw-net.service',net,mode=0o644)
            run_checked(['systemctl','daemon-reload'])
            run_checked(['systemctl','start','mosquitto'])
            # The network witness runs as the service user (in group adm) and must read the broker log;
            # Mosquitto writes it 0600, which silently left every sender count null.
            if os.path.exists(log_path):
                run_checked(['chgrp','adm',log_path]); run_checked(['chmod','0640',log_path])
            check_admin(admin)
            # Baseline connections distinguish auth failures from transport failure.
            from .mqtt_probe import probe
            for service in SERVICES:
                if probe('127.0.0.1',1883,username=service,password=values[service])['connect']!=0:
                    raise RuntimeError('A service account could not authenticate')
            for unit in UNITS:
                if unit=='sw-net' or status.get(unit): run_checked(['systemctl','start',unit+'.service'])
            time.sleep(2)
            for unit in UNITS:
                if unit=='sw-net' or status.get(unit): run_checked(['systemctl','is-active',unit+'.service'])
            run_checked(['systemctl','enable','sw-net.service'])
            private_write(state/'status','active\n')
            run_checked(['systemctl','stop','sw-security-v2-rollback.timer'])
            print('Hub locked down; private env files and A2 authority installed. Run verify.py and live_test.py.')
        except BaseException:
            rollback(state)
            run_checked(['systemctl','stop','sw-security-v2-rollback.timer'])
            raise
