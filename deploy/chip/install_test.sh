#!/usr/bin/env bash
# Run from a checkout on the Mac/laptop. Copies the chip service to the TEST LinuxONE and installs
# sw-chip.service there. Needs chip-remote.env + ca.crt (from BUILD: security_v2/scripts/add_chip.py)
# in $SW_CHIP_SECRETS (default ./.chip-secrets). Never prints the env file.
set -euo pipefail
HOST=${SW_CHIP_TEST_HOST:-linux1@148.100.79.93}
KEY=${SW_CHIP_TEST_KEY:-$HOME/.ssh/claudetest.pem}
SECRETS=${SW_CHIP_SECRETS:-./.chip-secrets}
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
SSH=(ssh -4 -i "$KEY" "$HOST")
cd "$ROOT"
"${SSH[@]}" 'mkdir -p ~/shared/chip/repo ~/shared/chip/pylib'
rsync -a -e "ssh -4 -i $KEY" --exclude __pycache__ --exclude results --relative chip ml_v2/stretch "$HOST":shared/chip/repo/
# paho-mqtt into a side folder; IBM's /opt/venv is left unchanged.
"${SSH[@]}" 'test -d ~/shared/chip/pylib/paho || docker exec notebook /opt/venv/bin/pip install -q --target /home/ibm-user/shared/chip/pylib paho-mqtt==2.1.0'
if [ -f "$SECRETS/chip-remote.env" ]; then
  scp -4 -q -i "$KEY" "$SECRETS/chip-remote.env" "$SECRETS/ca.crt" "$HOST":shared/chip/
  "${SSH[@]}" 'chmod 600 ~/shared/chip/chip-remote.env; chmod 644 ~/shared/chip/ca.crt'
fi
scp -4 -q -i "$KEY" deploy/chip/sw-chip.service "$HOST":/tmp/sw-chip.service
"${SSH[@]}" 'sudo install -m 0644 /tmp/sw-chip.service /etc/systemd/system/sw-chip.service && sudo systemctl daemon-reload && sudo systemctl enable sw-chip.service && sudo systemctl restart sw-chip.service && sleep 8 && systemctl is-active sw-chip.service && journalctl -u sw-chip.service -n 5 --no-pager'
