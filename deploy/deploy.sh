#!/bin/bash
# Run on the Mac. No source changes, no keys/env files transferred, no remote data deleted.
set -euo pipefail
umask 077
ROOT=$(cd "$(dirname "$0")/.." && pwd)
REMOTE=linux1@148.100.112.19
KEY=${SW_SSH_KEY:-$HOME/.ssh/claudebuild.pem}
DRY=0
case "${1:-}" in
  --dry-run) DRY=1 ;;
  --help|-h) echo 'Usage: deploy/deploy.sh [--dry-run]'; exit 0 ;;
  '') ;;
  *) echo 'Unknown argument' >&2; exit 2 ;;
esac
if [ "$#" -gt 1 ]; then echo 'Only --dry-run is supported' >&2; exit 2; fi
if [ "$DRY" -eq 1 ]; then
  cat <<'PLAN'
DRY RUN — no network, npm, rsync or remote commands executed.
1. Copy frontend to a temporary directory; exclude node_modules, dist, secrets.
2. npm ci; npm run build with backend runtime, API /api, WebSocket same origin.
3. ssh -4 to linux1@148.100.112.19; check existing ~/sw/.venv, system packages and .env.
4. rsync repo to /home/linux1/sw/app (include ml/ models; exclude secrets, caches and local outputs).
5. Install missing universal Python wheels only; editable --no-deps --no-build-isolation common/simulator/brain/attacks/backend.
6. Rsync the temporary frontend/dist to /home/linux1/sw/app/frontend/dist.
7. Install four systemd units; daemon-reload; enable and restart; print sanitized status + HTTP health.
Existing ~/sw/.env, packs, data and runs are preserved. No rsync --delete.
PLAN
  exit 0
fi
for utility in ssh rsync npm python3; do command -v "$utility" >/dev/null || { echo "Missing $utility" >&2; exit 1; }; done
[ -r "$KEY" ] || { echo 'SSH key is not readable' >&2; exit 1; }
[ -f "$ROOT/frontend/package-lock.json" ] || { echo 'frontend/package-lock.json is required for npm ci' >&2; exit 1; }
BUILD=$(mktemp -d "${TMPDIR:-/tmp}/sw-build.XXXXXX")
trap 'rm -rf -- "$BUILD"' EXIT INT TERM
# Copy/build only in a temporary directory, including an empty WS env to override inherited URLs.
rsync -a --exclude node_modules --exclude dist --exclude '.env*' --exclude '*.tsbuildinfo' "$ROOT/frontend/" "$BUILD/frontend/"
(
  cd "$BUILD/frontend"
  export npm_config_cache="$BUILD/npm-cache"
  npm ci --no-audit --no-fund >"$BUILD/npm-ci.log" 2>&1 || { echo 'npm ci failed; npm output withheld (possible registry credentials)' >&2; exit 1; }
  # An unset optional WS URL derives /ws from window.location in the frontend adapter.
  env -u VITE_SENTINELWARD_WS_URL VITE_SENTINELWARD_RUNTIME_MODE=backend VITE_SENTINELWARD_API_BASE_URL=/api npm run build >"$BUILD/npm-build.log" 2>&1 || {
    echo 'Frontend build failed; inspect it in an isolated temp copy (build output withheld)' >&2; exit 1;
  }
)
[ -s "$BUILD/frontend/dist/index.html" ] || { echo 'Build has no dist/index.html' >&2; exit 1; }
SSH=(ssh -4 -i "$KEY" -o BatchMode=yes -o ConnectTimeout=15)
# Quote key for rsync's remote-shell string; disallow shell metacharacters in key overrides.
case "$KEY" in *[!a-zA-Z0-9_./-]*) echo 'SW_SSH_KEY must use a path without shell metacharacters or spaces' >&2; exit 2 ;; esac
RSH="ssh -4 -i $KEY -o BatchMode=yes -o ConnectTimeout=15"
"${SSH[@]}" "$REMOTE" 'bash -se' <<'REMOTE_PREFLIGHT'
set -euo pipefail
[ "$(uname -m)" = s390x ] || { echo 'Expected s390x server' >&2; exit 1; }
[ -x /home/linux1/sw/.venv/bin/python ] && [ -r /home/linux1/sw/.env ]
/home/linux1/sw/.venv/bin/python - <<'PY'
import numpy, scipy, pandas, yaml, psutil
from pathlib import Path
import sys
for module in (numpy, scipy, pandas):
    if 'dist-packages' not in str(Path(module.__file__).resolve()):
        raise SystemExit('Scientific package must come from Ubuntu: ' + module.__name__)
if sys.prefix == sys.base_prefix:
    raise SystemExit('Expected existing venv')
print('Ubuntu scientific packages verified')
PY
mkdir -p /home/linux1/sw/app /home/linux1/sw/runs/simulator /home/linux1/sw/runs/attacks
REMOTE_PREFLIGHT
rsync -a -e "$RSH" \
  --exclude .git --exclude '.venv*' --exclude node_modules --exclude __pycache__ \
  --exclude .pytest_cache --exclude .mypy_cache --exclude .ruff_cache --exclude '.env*' \
  --exclude '*.pem' --exclude '*.key' --exclude '.aws' --exclude '.ssh' --exclude .codex --exclude .agents \
  --exclude '*.egg-info' --exclude '*.pyc' --exclude '*.tsbuildinfo' \
  --exclude /frontend/dist --exclude /tests_system/out --exclude /tests_system/results \
  --exclude /packs --exclude /runs --exclude /simulator/runs --exclude /attacks/runs \
  "$ROOT/" "$REMOTE:/home/linux1/sw/app/"
"${SSH[@]}" "$REMOTE" 'bash -se' <<'REMOTE_INSTALL'
set -euo pipefail
cd /home/linux1/sw/app
/home/linux1/sw/.venv/bin/python deploy/install_deps.py
# --no-build-isolation prevents setuptools bootstrap from resolving native dependencies.
# Capture installer output: index URLs can contain secrets. Emit only a fixed error.
if ! /home/linux1/sw/.venv/bin/python -m pip install --disable-pip-version-check --no-deps --no-build-isolation \
  -e common -e simulator -e brain -e attacks -e backend >/home/linux1/sw/.editable-install.log 2>&1; then
  chmod 600 /home/linux1/sw/.editable-install.log
  echo 'Editable package install failed; inspect the protected server log locally' >&2
  exit 1
fi
rm -f /home/linux1/sw/.editable-install.log
REMOTE_INSTALL
rsync -a -e "$RSH" "$BUILD/frontend/dist/" "$REMOTE:/home/linux1/sw/app/frontend/dist/"
"${SSH[@]}" "$REMOTE" 'bash -se' <<'REMOTE_START'
set -euo pipefail
for service in api brain sim attacks; do
  sudo -n install -m 644 "/home/linux1/sw/app/deploy/systemd/sw-$service.service" /etc/systemd/system/
done
sudo -n systemctl daemon-reload
sudo -n systemctl enable sw-api sw-brain sw-sim sw-attacks >/dev/null
sudo -n systemctl restart sw-api sw-brain sw-sim sw-attacks
sleep 3
# systemctl status/journal may include command arguments or application secrets; print state fields only.
failed=0
for service in api brain sim attacks; do
  printf 'sw-%s: ' "$service"
  systemctl show "sw-$service" --property=ActiveState,SubState,MainPID --value | tr '\n' ' '
  printf '\n'
  systemctl is-active --quiet "sw-$service" || failed=1
done
/home/linux1/sw/.venv/bin/python - <<'PY'
import json, time, urllib.request
for attempt in range(10):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2) as response:
            health = json.load(response)
        print('API health:', json.dumps({k: health.get(k) for k in ('ok','mqtt_connected','db_ok','storage','durable')}))
        if not health.get('ok') or not health.get('mqtt_connected'):
            raise RuntimeError()
        break
    except Exception:
        if attempt == 9:
            raise SystemExit('API health check failed; inspect journal locally on server')
        time.sleep(1)
PY
exit "$failed"
REMOTE_START
echo 'Deploy finished. Access via: ssh -4 -i ~/.ssh/claudebuild.pem -N -L 8000:127.0.0.1:8000 linux1@148.100.112.19'
