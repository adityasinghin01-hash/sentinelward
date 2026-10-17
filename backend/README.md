# SentinelWard backend (`sw_api`)

FastAPI + WebSocket + PostgreSQL server for the 13 SentinelWard screens and the Demo button. It
subscribes to every hub message (MQTT, via `sw_common.Bus`), keeps the live ward in memory, stores
everything in PostgreSQL in one-second batches, serves `/api/...` and pushes live bed updates on
`/ws`. It retains available last trusted values when data becomes untrusted; this is not a measured guarantee of screen continuity (see `docs/evidence/WARD-RUN.md`). Endpoint reference: [API.md](API.md)
and the OpenAPI page at `/docs`.

## Run it

From the repository root (LinuxONE: Ubuntu 24.04, s390x, Python 3.12, Ubuntu's `libpq5`):

```sh
python3 -m venv .venv
.venv/bin/pip install ./common ./backend          # add './backend[test]' on a dev machine
SW_PG_DSN=postgresql://sentinelward@localhost/sentinelward .venv/bin/sw-api
```

`SW_PG_DSN=memory` runs without a database (development only: nothing survives a restart). The
database must exist; `schema.sql` (idempotent) is applied at every start-up and ward.yaml is synced
into `beds`/`patients`. Create it once:

```sh
sudo -u postgres createuser sentinelward
sudo -u postgres createdb -O sentinelward sentinelward
```

Dependencies: fastapi, pydantic, plain uvicorn (selected explicitly: `asyncio` loop, `h11`,
`websockets-sansio`), `websockets` (pure Python, needed for the WebSocket protocol), psycopg 3 in
pure-Python mode with the system libpq (no psycopg-binary, no psycopg_pool), paho-mqtt, PyYAML and
sw_common. No uvloop or httptools. Run one worker: the live ward and sessions belong to the process.

When `web/dist/index.html` exists the backend also serves the built screens at `/`, so screens,
API and WebSocket share one origin on port 8000. Set `SW_FRONTEND_DIST` for wheel installs.

## Settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `MQTT_HOST`, `MQTT_PORT` | `127.0.0.1`, `1883` | Hub; the bus reconnects on its own |
| `MQTT_USER`, `MQTT_PASS` | unset | Optional credentials (a password needs a user) |
| `SW_PG_DSN` | `memory` | PostgreSQL DSN, or `memory` |
| `SW_WARD_YAML`, `SW_USERS_YAML` | bundled files | 12 beds (made-up patients) and 6 demo users with demo PINs |
| `SW_API_HOST`, `SW_API_PORT` | `127.0.0.1`, `8000` | Listen address |
| `SW_DEMO_ROLE_LOGIN` | `true` | Accept the screens' `{role}` login; `false` = PIN only |
| `SW_SESSION_TTL_S` | `28800` | Session lifetime |
| `SW_FRONTEND_DIST` | `../web/dist` | Built screens served at `/` |

## systemd

```ini
# /etc/systemd/system/sentinelward-api.service
[Unit]
Description=SentinelWard API
After=network-online.target postgresql.service mosquitto.service
Wants=postgresql.service mosquitto.service

[Service]
User=sentinelward
WorkingDirectory=/srv/sentinelward
Environment=SW_PG_DSN=postgresql://sentinelward@localhost/sentinelward
Environment=SW_FRONTEND_DIST=/srv/sentinelward/web/dist
ExecStart=/srv/sentinelward/.venv/bin/sw-api
Restart=on-failure
KillSignal=SIGINT
TimeoutStopSec=20

[Install]
WantedBy=multi-user.target
```

`sudo systemctl daemon-reload && sudo systemctl enable --now sentinelward-api`. SIGINT/SIGTERM shut
down cleanly: MQTT stops first, queued publications are retried once, the batch writer drains
(up to five attempts) and both database connections close.

## SSH tunnel for the screens

Only SSH is open on the server. From a laptop:

```sh
ssh -N -L 8000:127.0.0.1:8000 <user>@<linuxone-host>
```

then open `http://localhost:8000/` (screens) or `http://localhost:8000/docs` (API).

## How it works

- **Ingest.** The MQTT thread only copies the message and calls `loop.call_soon_threadsafe`. On the
  event loop each message is validated with `sw_common.validate` and checked against its topic; an
  invalid one is counted (`/api/health.invalid_messages`) and logged once per topic. Valid messages
  update memory, are queued for the database and pushed to WebSocket clients in the same step.
- **Database.** `writer.py` commits everything queued at most once per second in one transaction
  (consecutive rows of the same statement go in one pipelined `executemany`). All statements are
  upserts or `ON CONFLICT DO NOTHING`, so a failed batch is rolled back and retried whole after a
  reconnect without duplicates. Raw waveforms are never stored: `vitals_1s` keeps one row per bed
  per second. After a restart the newest 30 minutes per bed, recent verdicts, latest scores, alerts,
  actions, records, assignments, open nurse calls and unsent publications are loaded back.
- **Outbox.** Every publication (requests, bedside checks, staff actions, demo control) is validated,
  stored, then put in the outbox; it leaves the outbox only when the hub accepts it, in order. In
  PostgreSQL mode the outbox survives a restart.
- **Retain available values.** Each bed keeps 30 minutes of per-second values in RAM. A bed is trusted while the
  latest verdict has `last_trusted_ts = null` and no isolation (`disable_client`/`set_bed_untrusted`
  not lifted by `enable_client` or an undo) is in force. Otherwise it shows the newest *trusted* values
  at or before the earliest boundary (`last_trusted_ts`, or the isolation moment); older pins come from
  the database. After 5 s without vitals the bed is offline but keeps showing its values (the trusted
  pin if it is untrusted; if no trusted pin exists it uses flagged last values). A bed that never sent data shows `vitals: null`. B07’s 88 legacy counts per run are a counter artefact before first data; 0 empty samples after first data in all four runs (N/F1/F2/F3). Rendered-screen continuity was not measured (`../docs/evidence/WARD-RUN.md`). Missing values are null,
  0 stays 0; manual readings are kept apart (`manual`) and never replace monitor values.
- **Actions with changing results.** Agents re-publish the same `action_id` when a result changes
  (`pending` → `ok`/`failed`); the newest version replaces the stored one and a late `failed`
  reverses its effect (an isolation is lifted; a failed undo puts the isolation back).
- **Demo reset.** Publishes `reset`, empties all run tables (beds, patients and `demo_runs` stay),
  drops queued old-run rows and publications, and rejects any message with a source time at or
  before the reset (also after a restart), so retained pre-reset verdicts cannot come back.
- **WebSocket.** 12 `bed.updated` messages first, then critical changes immediately and telemetry at
  most once per bed per second. Past 500 queued messages a client loses telemetry first (never
  verdict/alert/action changes); past 2,000 it is disconnected.

## Tests

```sh
.venv/bin/pytest -q backend/tests                 # offline: fake bus and clock, memory store
SW_TEST_PG=postgresql://localhost/sw_test .venv/bin/pytest -q backend/tests/test_postgres.py
.venv/bin/pytest -q brain/tests attacks/tests common/tests
```

`SW_TEST_PG` must point at a **disposable** database: the PostgreSQL tests drop and recreate its
`public` schema. They cover schema idempotence, persisted rows and trust marks, warm start (never
blank across a restart), pins older than RAM, the durable outbox, reset barriers and retry after a
lost connection. `test_network_ws.py` starts real Uvicorn on a localhost port. Timings measured on a
laptop do not establish LinuxONE performance (targets: `/api/ward` < 50 ms, 30-minute history
< 100 ms, verdict to WebSocket < 100 ms).

After merging the fresh screens, run their contract checks from `web/` against real backend
responses. The earlier adapter harness targets retired screens and does not verify this UI.
