#!/bin/bash
# Install only the fresh agents; hub setup supplies private credentials separately.
set -euo pipefail
umask 077
SW_APP=$(cd "$(dirname "$0")/.." && pwd)
SW_ROOT=${SW_ROOT:-"$HOME/sw"}
SW_VENV=${SW_VENV:-"$SW_ROOT/.venv"}
SW_AGENTS_ENV=${SW_AGENTS_ENV:-"$SW_ROOT/agents.env"}
SW_AGENTS_STATE=${SW_AGENTS_STATE:-"$SW_ROOT/agents-data"}
export SW_APP SW_VENV SW_AGENTS_ENV SW_AGENTS_STATE
[ -f "$SW_APP/agents_v2/pyproject.toml" ] || { echo 'agents_v2/ is missing; merge the fresh agents before installation' >&2; exit 1; }
if [[ $(uname -s) != Linux || $(uname -m) != s390x ]]; then
    echo 'This installer targets Ubuntu s390x only.' >&2; exit 1
fi
if [[ $(id -u) == 0 ]]; then
    echo 'Run as the deployment user with sudo access, not root.' >&2; exit 1
fi
[ -x "$SW_VENV/bin/python" ] || { echo 'Existing Python venv required' >&2; exit 1; }
[ -r "$SW_AGENTS_ENV" ] || { echo 'Create a private agents.env with the fresh SW_MQTT_* settings; see deploy/agents.env.example' >&2; exit 1; }
"$SW_VENV/bin/python" - <<'PY'
import os, sys
from pathlib import Path
if sys.version_info[:2] != (3, 12):
    raise SystemExit('Agents require Python 3.12')
if Path(os.environ['SW_AGENTS_ENV']).stat().st_mode & 0o077:
    raise SystemExit('agents.env must have mode 0600')
PY
sudo -n true
mkdir -p "$SW_AGENTS_STATE"
SW_INSTALL_LOG=$(mktemp "$SW_ROOT/agents-install.XXXXXX")
SW_UNIT_TMP=$(mktemp "$SW_ROOT/agents-unit.XXXXXX")
trap 'rm -f "$SW_INSTALL_LOG" "$SW_UNIT_TMP"' EXIT
if systemctl cat sw-agents.service >/dev/null 2>&1; then sudo -n systemctl stop sw-agents.service; fi
if ! "$SW_VENV/bin/python" -m pip install -r "$SW_APP/deploy/requirements-agents.txt" >"$SW_INSTALL_LOG" 2>&1 \
    || ! "$SW_VENV/bin/python" -m pip install --no-deps "$SW_APP/common" "$SW_APP/security_v2" "$SW_APP/agents_v2" >>"$SW_INSTALL_LOG" 2>&1; then
    install -m 600 "$SW_INSTALL_LOG" "$SW_AGENTS_STATE/install-error.log"
    echo 'Agent installation failed; inspect the private install-error.log.' >&2; exit 1
fi
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
echo 'Fresh sw-agents installed. Verify journal locally; apply security_v2 hub setup for secured containment.'
