"""Add (or remove) the AI-chip client on a hub that is already locked down, without a re-setup.

setup.py writes the full dynsec config only once (later runs keep live credentials and
containment state). This applies exactly policy.roles()'s 'chip' role and the backend's
extra ward/chip/+ subscription to the running broker over the admin's TLS $CONTROL
channel (the password never enters argv), so verify.py's exact role check passes after it.
Idempotent; --remove undoes it.
"""
import json
import os
import threading
import uuid
from pathlib import Path

from .io import private_read, private_write
from .policy import CHIP_TOPIC, CONTROL, credentials, roles

CHIP = 'chip'


def wanted_acls(rolename):
    return [a for r in roles() if r['rolename'] == rolename for a in r['acls']]


def _key(a):
    return (a['acltype'], a['topic'])


def parse_options(text):
    """mosquitto_ctrl -o file: '-h host', '-p port', '--cafile path', '-u user', '-P password'."""
    out = {}
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2:
            out[parts[0]] = parts[1]
    return {'host': out['-h'], 'port': int(out['-p']), 'ca': out.get('--cafile'),
            'username': out['-u'], 'password': out['-P']}


class ControlChannel:
    """One request/response at a time on $CONTROL/dynamic-security/v1."""

    def __init__(self, options):
        from paho.mqtt import client as mqtt
        self.o = options
        self.c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id='sw-chip-admin-' + uuid.uuid4().hex[:8],
                             protocol=mqtt.MQTTv5)
        self.c.username_pw_set(options['username'], options['password'])
        if options.get('ca'):
            self.c.tls_set(ca_certs=options['ca'])
        self.ready = threading.Event(); self.got = threading.Event(); self.reply = None
        self.c.on_connect = lambda c, u, f, r, p: (c.subscribe(CONTROL + '/response', qos=1) if not r.is_failure else None)
        self.c.on_subscribe = lambda *a: self.ready.set()
        self.c.on_message = self._message

    def _message(self, c, u, msg):
        try:
            self.reply = json.loads(msg.payload)
        except ValueError:
            self.reply = None
        self.got.set()

    def __enter__(self):
        self.c.connect(self.o['host'], self.o['port'], keepalive=10)
        self.c.loop_start()
        if not self.ready.wait(5):
            raise RuntimeError('Dynsec control channel unavailable')
        return self

    def __exit__(self, *exc):
        self.c.disconnect(); self.c.loop_stop()

    def __call__(self, command):
        self.got.clear(); self.reply = None
        self.c.publish(CONTROL, json.dumps({'commands': [command]}), qos=1)
        if not self.got.wait(5) or not self.reply:
            raise RuntimeError('No dynsec response')
        resp = self.reply['responses'][0]
        return resp


def plan_add(get, password, have_client):
    """Commands that bring chip + backend roles to policy; get(rolename) -> current acls or None."""
    cmds = []
    for rolename in (CHIP, 'backend'):
        current = get(rolename)
        if current is None:
            cmds.append({'command': 'createRole', 'rolename': rolename})
            current = []
        have = {_key(a) for a in current}
        for a in wanted_acls(rolename):
            if _key(a) not in have:
                cmds.append({'command': 'addRoleACL', 'rolename': rolename, 'acltype': a['acltype'],
                             'topic': a['topic'], 'priority': a.get('priority', 0), 'allow': a['allow']})
    if have_client:
        cmds += [{'command': 'setClientPassword', 'username': CHIP, 'password': password},
                 {'command': 'addClientRole', 'username': CHIP, 'rolename': CHIP, 'priority': 0}]
    else:
        cmds.append({'command': 'createClient', 'username': CHIP, 'password': password,
                     'roles': [{'rolename': CHIP, 'priority': 0}]})
    return cmds


def plan_remove(have_client, have_role):
    cmds = [{'command': 'removeRoleACL', 'rolename': 'backend', 'acltype': t, 'topic': CHIP_TOPIC}
            for t in ('subscribePattern', 'publishClientReceive')]
    if have_client:
        cmds.append({'command': 'deleteClient', 'username': CHIP})
    if have_role:
        cmds.append({'command': 'deleteRole', 'rolename': CHIP})
    return cmds


def _role_acls(ctl, rolename):
    r = ctl({'command': 'getRole', 'rolename': rolename})
    if r.get('error'):
        return None
    return r['data']['role'].get('acls', [])


def apply(state, service_state, *, server_ip, remote_ca, remove=False, ctl_factory=ControlChannel, owner=None):
    """Root-side entry point. Writes <service_state>/env/chip-remote.env for the remote chip host."""
    state, service_state = Path(state), Path(service_state)
    options = parse_options(private_read(service_state / 'admin.conf'))
    with ctl_factory(options) as ctl:
        client = ctl({'command': 'getClient', 'username': CHIP})
        have_client = not client.get('error')
        if remove:
            cmds = plan_remove(have_client, _role_acls(ctl, CHIP) is not None)
        else:
            secretfile = state / 'credentials.json'
            values = json.loads(private_read(secretfile))
            if CHIP not in values:
                values[CHIP] = credentials()[CHIP]
                private_write(secretfile, json.dumps(values))
            cmds = plan_add(lambda r: _role_acls(ctl, r), values[CHIP], have_client)
        for cmd in cmds:
            r = ctl(cmd)
            err = r.get('error')
            if err and not (remove and 'not found' in err.lower()):
                raise RuntimeError(f"dynsec {cmd['command']} failed")
        if not remove:
            env = (f'SW_CHIP_HOST={server_ip}\nSW_CHIP_PORT=8883\nSW_CHIP_CA={remote_ca}\n'
                   f'SW_CHIP_USER={CHIP}\nSW_CHIP_PASSWORD={values[CHIP]}\nSW_CHIP_CLIENT_ID=sw-chip\n')
            path = service_state / 'env' / 'chip-remote.env'
            private_write(path, env)
            if owner is not None:
                os.chown(path, owner.pw_uid, owner.pw_gid)
            # Local env too (setup.py's format), for running the chip client on the hub itself.
            local = ''.join(f'{k}={v}\n' for k, v in {
                'SW_CHIP_HOST': '127.0.0.1', 'SW_CHIP_PORT': '1883', 'SW_CHIP_USER': CHIP,
                'SW_CHIP_PASSWORD': values[CHIP]}.items())
            private_write(service_state / 'env' / 'chip.env', local)
            if owner is not None:
                os.chown(service_state / 'env' / 'chip.env', owner.pw_uid, owner.pw_gid)
        # Read back: the live roles must now equal policy (or be gone).
        chip_acls = _role_acls(ctl, CHIP)
        backend = _role_acls(ctl, 'backend') or []
        norm = lambda acls: sorted(_key(a) for a in acls)
        if remove:
            ok = chip_acls is None and not any(a['topic'] == CHIP_TOPIC for a in backend)
        else:
            ok = norm(chip_acls or []) == norm(wanted_acls(CHIP)) and norm(backend) == norm(wanted_acls('backend'))
        if not ok:
            raise RuntimeError('Live dynsec roles do not match policy after the change')
    return [c['command'] for c in cmds]
