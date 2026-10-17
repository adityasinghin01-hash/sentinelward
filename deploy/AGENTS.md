# Fresh agents on the LinuxONE stack

The service now installs `agents_v2/` (package `sw_agents`) and launches it through
`security_v2/scripts/run_agents.py`. Merge the fresh agents before using the installer.
The old LangGraph CLI, migration runner and separate PostgreSQL database are no longer required.

## Install on the server

Use the existing Python 3.12 venv at `~/sw/.venv`. Create `~/sw/agents.env` with mode 0600
from `deploy/agents.env.example`, using the hub-issued agents MQTT account. Check the merged
`agents_v2/` env example for its state, Telegram and timing settings before installation.
Run `./deploy/agents_install.sh` from the copied checkout during a maintenance window.
The installer only stops/reinstalls/restarts sw-agents and preserves existing state and env files.
It does not configure or restart the hub, backend or simulator, and does not provision a database.

Defaults are `SW_ROOT=~/sw`, `SW_VENV=~/sw/.venv`, `SW_AGENTS_ENV=~/sw/agents.env`, and
`SW_AGENTS_STATE=~/sw/agents-data`. The unit runs in that writable state directory; all other
home paths remain read-only. Ensure merged agents' state/evidence paths resolve there.
Dependency/build failures are retained privately in `agents-data/install-error.log` (0600).

## Secured hub integration

The launcher inherits `SW_MQTT_HOST`, `SW_MQTT_PORT`, `SW_MQTT_USER`, `SW_MQTT_PASS`,
`SW_DYNSEC_OPTIONS`, `SW_CONTAIN_AUDIT`, and `SW_MONITOR_CREDENTIALS`.
`security_v2` setup writes the private environment and the sw-agents unit drop-in.
If installing agents after hub setup, follow `security_v2/SECURITY.md` for rollback and reprovisioning
between demos so snapshots include the agent unit. Never paste env files or journal secrets.

The existing agents ACL stays unchanged. Review missing A3 evidence/A4 fleet-hunt subscriptions
before acceptance; see the cleanup report. No expanded permissions are granted automatically.
After merging, run `python -m pytest agents_v2/tests` and verify real hub containment/undo,
alerts, records, reset and optional delivery on LinuxONE. Local unit tests do not establish those results.
