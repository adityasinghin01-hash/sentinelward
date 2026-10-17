#!/usr/bin/env bash
# Creates container secrets offline; preserves credentials on repeat runs. Never prints secrets.
set -euo pipefail
cd "$(dirname "$0")"
umask 077
python3 - <<'PY'
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets


def directory(path):
    if path.is_symlink():
        raise SystemExit(f'Refusing symlink: {path}')
    path.mkdir(mode=0o700, exist_ok=True)
    path.chmod(0o700)


def private(path, value=None):
    if path.is_symlink():
        raise SystemExit(f'Refusing symlink: {path}')
    if value is not None and (not path.exists() or path.read_text() != value):
        # Temporary sibling + rename keeps a failed write from truncating a credential.
        temp = path.with_name(path.name + '.tmp')
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(value)
        temp.replace(path)
    path.chmod(0o600)
    return path.read_text()


def password_ok(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,}', value):
        raise SystemExit('Invalid existing credential; inspect private files; no automatic rotation')
    return value


db = Path('db_password.txt')
if not db.exists() and not db.is_symlink():
    private(db, secrets.token_urlsafe(32))
pw = password_ok(private(db).strip())
dsn = f'postgresql://sw_api:{pw}@db:5432/sentinelward'
private(Path('.env.containers'), f'SW_PG_DSN={dsn}\nDATABASE_URL={dsn}\n')

root = Path('.mqtt')
directory(root)
master = root / 'credentials.json'
users = {'sim': 'simulator', 'brain': 'brain', 'api': 'backend', 'attacks': 'attacks'}
if not master.exists() and not master.is_symlink():
    if any(root.iterdir()):
        raise SystemExit('Partial .mqtt state without credentials.json; inspect it before retrying')
    private(master, json.dumps({u: secrets.token_urlsafe(36) for u in users.values()}) + '\n')
values = json.loads(private(master))
if set(values) != set(users.values()):
    raise SystemExit('Unexpected MQTT accounts; inspect .mqtt/credentials.json')
for value in values.values():
    password_ok(value)

# mosquitto_passwd's $7$ format: PBKDF2-HMAC-SHA512, 12-byte salt, 64-byte key.
# Generated offline with stdlib only; no plaintext password in process arguments.
password_file = root / 'passwords'
if not password_file.exists() and not password_file.is_symlink():
    rows = []
    for user, password in values.items():
        salt = secrets.token_bytes(12)
        digest = hashlib.pbkdf2_hmac('sha512', password.encode(), salt, 210000, 64)
        rows.append(f'{user}:$7$210000${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}')
    private(password_file, '\n'.join(rows) + '\n')
rows = dict(line.split(':', 1) for line in private(password_file).splitlines())
if set(rows) != set(values):
    raise SystemExit('MQTT password file account mismatch')
for user, password in values.items():
    _, kind, count, salt, digest = rows[user].split('$')
    if kind != '7' or count != '210000' or not hmac.compare_digest(
        hashlib.pbkdf2_hmac('sha512', password.encode(), base64.b64decode(salt), int(count), 64),
        base64.b64decode(digest),
    ):
        raise SystemExit('MQTT password file mismatch; no automatic rotation')

directory(root / 'clients')
for service, user in users.items():
    password = values[user]
    env = {'MQTT_USER': user, 'MQTT_PASS': password,
           'SW_MQTT_USER': user, 'SW_MQTT_PASS': password}
    if service in ('brain', 'attacks'):
        prefix = 'SW_ATTACK_MQTT_' if service == 'attacks' else 'SW_MQTT_'
        env.update({prefix+'HOST': 'hub', prefix+'PORT': '1883', prefix+'TLS': '0',
                    prefix+'USERNAME': user, prefix+'PASSWORD': password})
    private(root / f'{service}.env', ''.join(f'{k}={v}\n' for k, v in env.items()))
    client_dir = root / 'clients' / service
    directory(client_dir)
    for client in ('mosquitto_pub', 'mosquitto_sub'):
        private(client_dir / client, f'-u {user}\n-P {password}\n')
print('Secrets ready: db_password.txt, .env.containers, .mqtt/ (files 0600; credentials preserved)')
PY
