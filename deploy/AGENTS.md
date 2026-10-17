# Agents on the merged LinuxONE stack

This is the runbook for `~/sw/app/agents`, using the existing LangGraph engine and durable
A1–A8 coordinators. The older `agents/docs/runbook.md` describes the isolated TLS/uv lab;
use **this file** for the merged localhost demo. No change to `deploy/deploy.sh` is required:
copy/sync these files with the rest of the app, then install agents separately.

## Install on the server

Server facts: Ubuntu 24.04 s390x, Python 3.12, anonymous Mosquitto at 127.0.0.1:1883,
PostgreSQL 16. The backend remains on port 8000; agents use loopback port 8088.

1. Finish the other agent's deployment first; avoid concurrent pip operations in the shared venv.
2. Provision **Rust >=1.88 and Cargo** using the server's approved toolchain method. Ubuntu's
   default Rust may be too old. The installer checks the compiler before changing services.
3. Keep `~/sw/.venv` created with `python3.12 -m venv --system-site-packages ~/sw/.venv`.
   The installer verifies numpy/scipy/pandas/sklearn resolve from `/usr/lib/python3/dist-packages`.
4. From the copied checkout, run:

   ```bash
   cd ~/sw/app
   ./deploy/agents_install.sh
   curl --fail http://127.0.0.1:8088/health/ready
   curl --fail http://127.0.0.1:8000/api/health
   sudo systemctl status sw-agents --no-pager
   ```

The installer defaults to the calling user, `~/sw/.venv`, `~/sw/agents.env`, and
`~/sw/agents-data`. `SW_ROOT`, `SW_VENV`, `SW_AGENTS_ENV`, `SW_AGENTS_STATE` can override these;
app path comes from the installer location. The unit is a template: the installer renders its
user/group/paths before writing `/etc/systemd/system/sw-agents.service`.

It creates a private `agents.env` with a generated password if missing, then creates **database
`sw_agents`, owned by login role `sw_agents`**. It refuses a different database/user/remote DSN,
checks ownership, never rotates an existing password, and never touches `sw_api` or `sentinelward`.
Only `sw_agents` receives the packaged Alembic migrations, LangGraph checkpointer tables and
APScheduler tables. Application tables live in `automation`; checkpointer tables remain in their
own database's public schema. Do not reuse the backend's `.env` or DSN.

Rerunning stops/reinstalls/restarts only sw-agents; it preserves the env file, role password,
database, evidence and audit history. Run between demos. The installer needs noninteractive sudo
for apt, local postgres psql, unit installation and systemctl. It does not enable Dynamic Security,
change the hub, open a firewall port, or start/restart any other project unit. Errors with possibly
sensitive diagnostic content are withheld or retained in `agents-data/install-error.log` (0600).
A failed migration leaves the unit stopped; correct the cause and rerun. No automatic schema rollback.

## Dependency and architecture limits

`requirements-agents.txt` pins runtime dependencies only. Install with pip; uv is unnecessary.
It never asks pip to install numpy/scipy/pandas/sklearn. The installer obtains Pillow, MarkupSafe,
PyYAML and libpq5 from Ubuntu. `PSYCOPG_IMPL=python` selects pure Python psycopg, avoiding psycopg[c]
and psycopg-binary. SQLAlchemy's optional C extension is disabled for its pure wheel build.

The unavoidable native builds with the existing LangGraph versions are **ormsgpack 1.13.0** and
**uuid-utils 0.17.1** (Rust/PyO3 through maturin). The ormsgpack source declares Rust >=1.88;
uuid-utils uses Rust edition 2024. Suitable Python 3.12 s390x wheels were not available in the
local index audit. All other pip requirements must have wheels or already be installed; the file
uses `--only-binary=:all:` with exceptions for those two and pure-build SQLAlchemy. The installer
installs build-essential/pkg-config; a full native build still needs verification on LinuxONE.
`orjson` is pinned to 3.11.9 because that version has a compatible s390x wheel; the previously
resolved 3.13.0 did not. The pinned binary-only dependency set was checked by cross-platform pip
download; that does not prove imports or linking on s390x.

## Configuration and delivery

`deploy/agents.env.example` documents every setting. Optional fields can remain empty.
Team mode explicitly permits anonymous **loopback** MQTT; the original TLS requirements remain
for other profiles. This is a demo, not a hospital security configuration. Any local process can
forge a producer on the current anonymous listener. Team requests trust the backend's authenticated
user IDs (`staff:sam` / `staff:admin` for IT/operator actions). Dynamic Security, real inventory,
registered role authorization and broker isolation still belong to Kartik's integration.

Without Telegram credentials A1 still publishes screen alerts and advances the ladder after 30 s
per step. Phone attempts are honestly logged as failed; alerts remain open/escalated. To enable
phone delivery set `SENTINEL_TELEGRAM_BOT_TOKEN` and `SENTINEL_TELEGRAM_RECIPIENTS_FILE` together.
The private JSON file maps the actual demo staff IDs to integer chat IDs, for example:

```json
{"staff:priya": 123456789, "staff:tom": 234567890, "staff:dr_mehta": 345678901}
```

Use your real chat IDs, chmod 0600, then `sudo systemctl restart sw-agents`.
There is one process/poller/scheduler; do not add Uvicorn workers or run a second instance.
Telegram callbacks and screen `ward/request` acknowledgements use the same A1 coordinator.

The public backend exposes `/api/health` and `/api/beds/Bxx`, not the isolated agent service's old
`/internal/v1/ward/assignments` or waveform endpoint. The team adapter uses those actual paths.
With a valid backend session token in `SENTINEL_BACKEND_SERVICE_TOKEN`, it reads current nurse
assignments; token expiry fails closed to the short-lived cached roster. Without a token it uses
the explicit demo roster matching `backend/ward.yaml`: B01–B06 Priya, B07–B12 Tom, Dr Mehta on call.
Update this adapter if the team's roster changes. Waveform images are unavailable through this API;
Telegram remains text-only. MQTT is the backend delivery path; no invented HTTP ingest endpoint.

An optional `SENTINEL_GRANITE_URL` uses the existing local OpenAI-compatible `/v1/chat/completions`
writer. Supply its model name and verified model-file SHA-256; the writer accepts only loopback
HTTP and validates every fact binding. Missing/invalid/timed-out output uses deterministic templates.
No model is downloaded or loaded by this installer, and no report is automatically sent.

## What runs

| Component | Behavior and honest limits |
|---|---|
| Engine | Existing LangGraph routing, allow-list, ingress deduplication, DB checkpoints and transactional outbox. |
| A1 | Nurse alert + 30 s ladder to next nurse, then both nurses + doctor; screen ack/escalate and bedside checks. A lower-priority tampering verdict cannot lower an emergency. |
| A2 | TAMPERING/BOTH or manual contain/isolate produces a **failed dry-run disable_client**, with no undo and no claim of isolation. Anonymous monitor senders cannot be individually disabled. Live broker adapter remains in the isolated harness, not wired to this listener. |
| A3 | Hashes captured MQTT transcripts, publishes incident/evidence/timeline records. Evidence is local files, not PCAP or independently authenticated network evidence. Resolve records the human decision without changing broker state. |
| A4 | Fleet list/watch bookkeeping for configured demo inventory, including v1.2 fleet_hunt. Watch levels are local; they do not reconfigure M5. The demo model is `demo-monitor`; `all` works. No hardware/firmware discovery is claimed. |
| A5 | Existing human confirmation API creates a CERT-In draft + six-hour clock; review_report opens an existing draft for review. It never sends a report. Confirmation/grants and edits still use the existing authenticated internal API on 8088 (see [Phase 5 runbook](../agents/docs/phase-5-runbook.md)); the main backend has no equivalent grant registration endpoint. No automatic first report is fabricated. |
| A6 | DRIFTING opens/updates a biomed ticket; repeated loose-sensor episodes use the existing threshold. Staff ticket edits in the main backend are not synchronized back to the agents' private ticket state. |
| A7 | Minute-by-minute two-hour screen-routed alert counts, workload records and threshold warnings; no nurse reassignment. Fixed demo nurse roster. |
| A8 | Existing shift/demo briefing, template fallback, Granite optional. Default demo briefing is at 19 wall-clock minutes; configured shifts/internal commands can trigger others. No fabricated suppressed-alarm or blind-time evidence. |
| M6 | Existing research scorer is packaged unchanged, disabled here because the brain also publishes M6. To enable it separately supply reviewed context/calibration files and enable both M6 and demo lifecycle; avoid two M6 producers. Its old full-script timing/context assumptions remain; it is not clinically validated. |
| A9 | Design only, no runtime actions. |

The team startup creates one initial run if no lifecycle state exists. Demo run/reset is consumed
without requiring research M6. Resets retire active alerts/timers/outbox and clear per-bed state,
keeping audit/evidence history. v1.2 scenario/speed fields are accepted; agents ignore them.
Team A2–A8 do not infer offline/attack status from the old hardcoded recording stop times; the
backend owns freshness/offline display. A8's demo timer is not scaled by simulator speed.

## Contract audit and local checks

See [the wire audit](../agents/docs/team-contract-audit.md) for every consumed/published topic
and the exact fixes. Ingress and the last MQTT outbox boundary use `sw_common.validate(strict=True)`;
all nullable fields remain present as JSON null. v1.2's explicitly permitted scenario/speed are
validated separately because this version of the shared package flags them as unknown in strict mode.

From the checkout (Python 3.12, pip):

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install ./common
.venv/bin/python -m pip install -e './agents[dev]'
cd agents
../.venv/bin/python -m pytest
```

PostgreSQL/broker/real-data/Granite integration tests explicitly skip without their private fixtures;
a green local suite with skips does not establish server acceptance. `tests/test_team_e2e.py` always
runs the real engine/coordinators/outbox with a fake broker and memory stores. To use a separately
started local anonymous Mosquitto, set `SENTINEL_TEAM_TEST_MQTT_PORT=<port>` for that test. It checks
B03 EMERGENCY → alert steps 1/2/3 → acked and TAMPERING → A2 dry-run for MON-03; every output is
strictly validated. It does not alter a monitor or contact Telegram.

On LinuxONE verify migrations/checkpointer setup, native imports/linking, service readiness,
backend MQTT ingestion, a real demo/reset, alert timing across restart and optional phone delivery.
The existing scheduler has a 30-second misfire grace; longer downtime needs explicit recovery testing.
Use `sudo journalctl -u sw-agents` privately; never paste env files, tokens, DSNs or raw patient data.
