import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sw_sec.chip_account import apply, parse_options, plan_add, wanted_acls
from sw_sec.io import private_read, private_write
from sw_sec.policy import CHIP_TOPIC, build_config, credentials, roles, service_env
from sw_common.topics import ALL_SUB


def test_chip_role_is_read_vitals_write_chip_only():
    r = {x['rolename']: x['acls'] for x in roles()}
    chip = sorted((a['acltype'], a['topic']) for a in r['chip'])
    assert chip == [('publishClientReceive', 'ward/bed/+/vitals'), ('publishClientSend', CHIP_TOPIC),
                    ('subscribePattern', 'ward/bed/+/vitals')]
    assert CHIP_TOPIC == 'ward/chip/+'
    # Backend keeps every contract subscription and may also read the chip messages.
    subs = {a['topic'] for a in r['backend'] if a['acltype'] == 'subscribePattern'}
    assert subs == {*ALL_SUB, CHIP_TOPIC}
    # Nobody else may publish on ward/chip/+, and chip cannot publish anything the ward acts on.
    for name, acls in r.items():
        if name != 'chip':
            assert not any(a['acltype'] == 'publishClientSend' and a['topic'].startswith('ward/chip') for a in acls)
    cfg = build_config(credentials())
    assert {c['username']: c['roles'] for c in cfg['clients']}['chip'] == [{'rolename': 'chip', 'priority': 0}]
    assert service_env('chip', {'chip': 'x'})['SW_CHIP_USER'] == 'chip'


class FakeDynsec:
    """Minimal in-memory dynsec: roles {name: [acl]}, clients {name: {password, roles}}."""

    def __init__(self, backend_acls):
        self.roles = {'backend': list(backend_acls)}
        self.clients = {}
        self.log = []

    def call(self, c):
        self.log.append(c['command'])
        k = c['command']
        if k == 'getRole':
            if c['rolename'] not in self.roles:
                return {'error': 'Role not found'}
            return {'data': {'role': {'rolename': c['rolename'], 'acls': self.roles[c['rolename']]}}}
        if k == 'getClient':
            return {'error': 'Client not found'} if c['username'] not in self.clients else {'data': {}}
        if k == 'createRole':
            self.roles[c['rolename']] = []
        elif k == 'addRoleACL':
            self.roles[c['rolename']].append({x: c[x] for x in ('acltype', 'topic', 'priority', 'allow')})
        elif k == 'createClient':
            self.clients[c['username']] = {'password': c['password'], 'roles': c['roles']}
        elif k == 'setClientPassword':
            self.clients[c['username']]['password'] = c['password']
        elif k == 'addClientRole':
            pass
        elif k == 'removeRoleACL':
            self.roles[c['rolename']] = [a for a in self.roles[c['rolename']]
                                         if (a['acltype'], a['topic']) != (c['acltype'], c['topic'])]
        elif k == 'deleteClient':
            self.clients.pop(c['username'], None)
        elif k == 'deleteRole':
            self.roles.pop(c['rolename'], None)
        return {}


class Ctl:
    def __init__(self, fake):
        self.fake = fake

    def __call__(self, options):
        return self

    def __enter__(self):
        return self.fake.call

    def __exit__(self, *a):
        pass


def setup_state(tmp_path):
    state, svc = tmp_path / 'state', tmp_path / 'svc'
    private_write(state / 'credentials.json', json.dumps({'admin': 'a', 'backend': 'b'}))
    private_write(svc / 'admin.conf', '-h 127.0.0.1\n-p 8883\n--cafile /x/ca.crt\n-u admin\n-P secret-admin\n')
    return state, svc


def old_backend():
    return [a for a in wanted_acls('backend') if a['topic'] != CHIP_TOPIC]


def test_apply_adds_exact_policy_idempotently_and_remove_undoes(tmp_path):
    state, svc = setup_state(tmp_path)
    fake = FakeDynsec(old_backend())
    done = apply(state, svc, server_ip='10.0.0.1', remote_ca='/c/ca.crt', ctl_factory=Ctl(fake))
    assert done.count('addRoleACL') == 5 and 'createClient' in done and 'createRole' in done
    pw = json.loads(private_read(state / 'credentials.json'))['chip']
    assert fake.clients['chip']['password'] == pw and len(pw) >= 40
    env = private_read(svc / 'env' / 'chip-remote.env')
    assert 'SW_CHIP_HOST=10.0.0.1\n' in env and 'SW_CHIP_PORT=8883\n' in env and 'SW_CHIP_CA=/c/ca.crt\n' in env
    assert (svc / 'env' / 'chip-remote.env').stat().st_mode & 0o777 == 0o600
    # Second run: no ACL changes, same password kept.
    again = apply(state, svc, server_ip='10.0.0.1', remote_ca='/c/ca.crt', ctl_factory=Ctl(fake))
    assert 'addRoleACL' not in again and 'createClient' not in again
    assert json.loads(private_read(state / 'credentials.json'))['chip'] == pw
    removed = apply(state, svc, server_ip='10.0.0.1', remote_ca='/c/ca.crt', remove=True, ctl_factory=Ctl(fake))
    assert 'deleteClient' in removed and 'chip' not in fake.roles and 'chip' not in fake.clients
    assert sorted((a['acltype'], a['topic']) for a in fake.roles['backend']) == \
        sorted((a['acltype'], a['topic']) for a in old_backend())


def test_plan_never_touches_other_roles():
    cmds = plan_add(lambda r: [] if r == 'backend' else None, 'pw', False)
    assert {c.get('rolename') for c in cmds if 'rolename' in c} <= {'chip', 'backend'}
    assert not any(c['command'].startswith(('delete', 'remove', 'disable')) for c in cmds)


def test_parse_options():
    o = parse_options('-h 127.0.0.1\n-p 8883\n--cafile /a b/ca.crt\n-u admin\n-P s3cret\n')
    assert o == {'host': '127.0.0.1', 'port': 8883, 'ca': '/a b/ca.crt', 'username': 'admin', 'password': 's3cret'}
