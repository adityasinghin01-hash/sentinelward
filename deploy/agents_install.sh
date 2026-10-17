#!/usr/bin/env bash
# Run as the deployment user on LinuxONE, from any working directory. No secrets on stdout.
set -euo pipefail
umask 077
SW_APP=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
SW_ROOT=${SW_ROOT:-"$HOME/sw"}
SW_VENV=${SW_VENV:-"$SW_ROOT/.venv"}
SW_AGENTS_ENV=${SW_AGENTS_ENV:-"$SW_ROOT/agents.env"}
SW_AGENTS_STATE=${SW_AGENTS_STATE:-"$SW_ROOT/agents-data"}
export SW_APP SW_ROOT SW_VENV SW_AGENTS_ENV SW_AGENTS_STATE
if [[ $(uname -s) != Linux || $(uname -m) != s390x ]]; then
    echo 'This installer targets Ubuntu s390x only.' >&2; exit 1
fi
if [[ $(id -u) == 0 ]]; then
    echo 'Run as the deployment user with sudo access, not root.' >&2; exit 1
fi
[[ -x "$SW_VENV/bin/python" ]] || { echo 'Missing ~/sw/.venv; create with Python 3.12 --system-site-packages.' >&2; exit 1; }
"$SW_VENV/bin/python" - <<'PY'
import sys, pathlib
if sys.version_info[:2] != (3, 12):
    raise SystemExit('Agents require Python 3.12')
cfg = pathlib.Path(sys.prefix, 'pyvenv.cfg').read_text()
if 'include-system-site-packages = true' not in cfg:
    raise SystemExit('The venv must use --system-site-packages')
for name in ('numpy', 'scipy', 'pandas', 'sklearn'):
    module = __import__(name)
    if '/usr/lib/python3/dist-packages/' not in module.__file__:
        raise SystemExit('Scientific dependencies must come from Ubuntu, not pip')
PY
command -v cargo >/dev/null && command -v rustc >/dev/null || {
    echo 'Rust toolchain required for ormsgpack and uuid-utils; see deploy/AGENTS.md.' >&2; exit 1;
}
"$SW_VENV/bin/python" - <<'RUST'
import re, subprocess
version = subprocess.check_output(['rustc', '--version'], text=True)
match = re.search(r'rustc (\d+)\.(\d+)', version)
if match is None or tuple(map(int, match.groups())) < (1, 88):
    raise SystemExit('Rust >=1.88 required by ormsgpack 1.13; see deploy/AGENTS.md')
RUST
sudo -n true
sudo -n apt-get install -y libpq5 python3-pil python3-markupsafe python3-yaml build-essential pkg-config >/dev/null
mkdir -p "$SW_AGENTS_STATE"
SW_INSTALL_LOG=$(mktemp "$SW_ROOT/agents-install.XXXXXX")
SW_UNIT_TMP=$(mktemp "$SW_ROOT/agents-unit.XXXXXX")
trap 'rm -f "$SW_INSTALL_LOG" "$SW_UNIT_TMP"' EXIT
# Only stop our own unit; migrations/pip must not race a running agents process.
if systemctl cat sw-agents.service >/dev/null 2>&1; then sudo -n systemctl stop sw-agents.service; fi
export DISABLE_SQLALCHEMY_CEXT=1 PSYCOPG_IMPL=python PIP_DISABLE_PIP_VERSION_CHECK=1
if ! "$SW_VENV/bin/python" -m pip install -r "$SW_APP/deploy/requirements-agents.txt" >"$SW_INSTALL_LOG" 2>&1; then
    echo "Dependency install failed. Private build log: $SW_AGENTS_STATE/install-error.log" >&2
    install -m 600 "$SW_INSTALL_LOG" "$SW_AGENTS_STATE/install-error.log"; exit 1
fi
# Local packages without dependency resolution cannot replace system scientific packages.
if ! "$SW_VENV/bin/python" -m pip install --no-deps "$SW_APP/common" "$SW_APP/agents" >"$SW_INSTALL_LOG" 2>&1; then
    install -m 600 "$SW_INSTALL_LOG" "$SW_AGENTS_STATE/install-error.log"
    echo 'Local package installation failed; inspect the private install-error.log.' >&2; exit 1
fi
"$SW_VENV/bin/python" - <<'PY'
import os, pathlib, secrets, subprocess
from urllib.parse import urlsplit, unquote
from dotenv import dotenv_values
from psycopg import sql
root = pathlib.Path(os.environ['SW_APP'])
path = pathlib.Path(os.environ['SW_AGENTS_ENV'])
if not path.exists():
    text = (root / 'deploy/agents.env.example').read_text()
    text = text.replace('@STATE_DIR@', os.environ['SW_AGENTS_STATE'])
    text = text.replace('CHANGE_ME', secrets.token_hex(32))
    with path.open('x') as stream: stream.write(text)
    path.chmod(0o600)
if path.stat().st_mode & 0o077:
    raise SystemExit('agents.env must have mode 0600')
values = dotenv_values(path)
u = urlsplit(values.get('SENTINEL_DATABASE_URL', ''))
if (u.scheme != 'postgresql' or u.hostname not in ('127.0.0.1', 'localhost')
        or u.path != '/sw_agents' or u.username != 'sw_agents' or u.port not in (None, 5432)):
    raise SystemExit('Refusing any DSN except local sw_agents database and sw_agents role')
password = unquote(u.password or '')
if not password or password == 'CHANGE_ME':
    raise SystemExit('Set a private sw_agents database password in agents.env')

def psql(statement):
    result = subprocess.run(['sudo', '-n', '-u', 'postgres', 'psql', '-X', '-qAt',
                             '-v', 'ON_ERROR_STOP=1', '-d', 'postgres'],
                            input=statement, text=True, capture_output=True)
    if result.returncode:
        raise SystemExit('PostgreSQL provisioning failed; check local PostgreSQL/sudo (details withheld)')
    return result.stdout.strip()
# Never rotate an existing role password or touch the backend's role/database.
exists = psql("SELECT 1 FROM pg_roles WHERE rolname='sw_agents';")
if exists != '1':
    psql(sql.SQL('CREATE ROLE sw_agents LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {};')
         .format(sql.Literal(password)).as_string())
if psql("SELECT 1 FROM pg_database WHERE datname='sw_agents';") != '1':
    psql('CREATE DATABASE sw_agents OWNER sw_agents;')
if psql("SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='sw_agents';") != 'sw_agents':
    raise SystemExit('Existing sw_agents database has another owner; left unchanged')
# Literal environment loading: no shell eval/source, and no credentials in argv.
for name, value in values.items():
    if value is not None and value != '': os.environ[name] = value
from sentinelward.config import Settings
from sentinelward.cli import run_migrations, init_checkpointer
import asyncio
try:
    settings = Settings(_env_file=None)
    settings.validate_files()
    if not settings.team_enabled:
        raise ValueError('team mode must be enabled')
    run_migrations(settings)
    asyncio.run(init_checkpointer(settings.database_url))
except Exception:
    raise SystemExit('Agent configuration/migrations failed (credentials withheld); verify agents.env and DB login') from None
PY
SW_UNIT_TMP="$SW_UNIT_TMP" "$SW_VENV/bin/python" - <<'PY'
import os, pathlib, pwd, grp
text = pathlib.Path(os.environ['SW_APP'], 'deploy/systemd/sw-agents.service').read_text()
values = {'USER': pwd.getpwuid(os.getuid()).pw_name, 'GROUP': grp.getgrgid(os.getgid()).gr_name,
          'APP': os.environ['SW_APP'], 'VENV': os.environ['SW_VENV'],
          'ENV': os.environ['SW_AGENTS_ENV'], 'STATE_DIR': os.environ['SW_AGENTS_STATE']}
for key, value in values.items():
    if any(c.isspace() for c in value) or '%' in value:
        raise SystemExit('Install paths must have no whitespace or systemd specifiers')
    text = text.replace('@' + key + '@', value)
pathlib.Path(os.environ['SW_UNIT_TMP']).write_text(text)
PY
sudo -n install -m 644 "$SW_UNIT_TMP" /etc/systemd/system/sw-agents.service
sudo -n systemctl daemon-reload
sudo -n systemctl enable --now sw-agents.service >/dev/null
echo 'sw-agents installed. Check http://127.0.0.1:8088/health/ready and /api/health on port 8000.'
