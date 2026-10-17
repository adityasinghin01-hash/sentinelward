# SentinelWard backend — Phase A

Phase A provides the live memory ward, validated MQTT ingestion, authenticated screen commands,
WebSocket fan-out and same-origin serving of an **already built** frontend. PostgreSQL, remaining
routes and the Node contract harness are Phase B. `schema.sql` is the existing draft and is not
applied by Phase A. Memory state, sessions and pending publications disappear on process exit.

From the repository root on Python 3.12+ (LinuxONE: Ubuntu 24.04, s390x):

```sh
python3 -m venv .venv
.venv/bin/pip install ./common './backend[test]'
SW_PG_DSN=memory .venv/bin/sw-api
```

Use the server's `python3-pytest` package if pytest is already provided there; the test extra is
only for development. Runtime dependencies are plain Uvicorn, FastAPI/Pydantic, paho-mqtt, PyYAML,
`websockets` and sw_common. The declared pure psycopg dependency is reserved for Phase B; it uses
system libpq, never psycopg-binary/pool. No uvloop/httptools required. One worker only: memory state
and sessions belong to that process. Runtime selects `asyncio`, `h11`, `websockets-sansio` explicitly.

Open `http://127.0.0.1:8000/` when `frontend/dist/index.html` exists. Source checkout defaults to the
sibling frontend directory; installed wheels should set `SW_FRONTEND_DIST` to the actual build.
The backend does not build or change frontend files. SPA routes fall back to index.html; missing
API and asset paths keep their 404s. API reference is at `/docs` and [API.md](API.md).

```sh
ssh -N -L 8000:127.0.0.1:8000 user@linuxone-host
```

| Setting | Default / meaning |
| --- | --- |
| `MQTT_HOST`, `MQTT_PORT` | `127.0.0.1`, `1883`; reconnects automatically |
| `MQTT_USER`, `MQTT_PASS` | Optional credentials; password requires user |
| `SW_API_HOST`, `SW_API_PORT` | `127.0.0.1`, `8000` |
| `SW_PG_DSN` | `memory`; other values fail explicitly until Phase B |
| `SW_WARD_YAML`, `SW_USERS_YAML` | Bundled 12-bed ward and fake demo identities/PINs |
| `SW_DEMO_ROLE_LOGIN` | `on`; accepts frontend `{role}` selection; `off` requires PIN |
| `SW_SESSION_TTL_S` | `28800`; expiring opaque session |
| `SW_FRONTEND_DIST` | Source checkout's `frontend/dist`; override for wheel installs |

PIN login and demo role login both set `sw_session` (HttpOnly, SameSite=Lax, Path=/; Secure under
HTTPS). HTTP and WS also accept Bearer and `?token=`. Cookie browser writes and WS require a matching
Origin when supplied. Role aliases: frontend `operator` = admin, `biomedical` = biomed. Staff identity
comes from the session, never from command bodies. Preview and health are public.

MQTT callbacks copy payloads and call `loop.call_soon_threadsafe`. All state mutation and WS fan-out
happen on the event loop; Phase A makes no SQL calls. Memory stores one scalar point per second,
original non-waveform event payloads, audit replacements and queued publications. Requests are saved
before publication and do not optimistically isolate a device, acknowledge an alert, or undo actions.
An accepted receipt means queued work, not execution. Disconnected publications remain in our outbox;
reset clears pending run work and increments an ingest generation barrier. Pre-reset source timestamps
are rejected, including retained verdicts. MQTT QoS1 can redeliver; receiving agents must deduplicate
request IDs. Once a publication has been handed to the broker/client, reset cannot retract it.

Trust freezes at the earliest verdict/isolation boundary. Only genuinely trusted historical points
can be pinned, with memory-store fallback beyond the 30-minute RAM buffer. An offline untrusted bed
continues showing its trusted pin. With no trusted point, last received readings stay visible and
explicitly untrusted. No-data `UNSURE`/`Awaiting verdict`/score 0 exists only in HTTP/WS projections.
Missing scalar values remain null; zero remains zero. Thin waveforms use empty channels when absent,
and frozen waveforms have a separate bounded cache. Manual readings remain separate from telemetry.

WebSockets start with 12 ordered `bed.updated` messages. Critical changes send immediately; telemetry
coalesces to at most one per bed per second. Above 500 queued messages, telemetry is removed first;
above 2,000 the client is disconnected. A 100ms ticker updates offline/feed status and retries outbox
work. `connection.changed` reports MQTT connection health. Sessions also expire on active sockets.

Example systemd service (adjust paths/user):

```ini
[Unit]
Description=SentinelWard API Phase A
After=network.target mosquitto.service
[Service]
User=sentinelward
WorkingDirectory=/srv/sentinelward
Environment=SW_PG_DSN=memory
Environment=SW_FRONTEND_DIST=/srv/sentinelward/frontend/dist
ExecStart=/srv/sentinelward/.venv/bin/sw-api
Restart=on-failure
[Install]
WantedBy=multi-user.target
```

```sh
.venv/bin/pytest -q backend/tests
.venv/bin/pytest -q brain/tests attacks/tests common/tests
```

Backend tests use pytest, fake clocks/bus and real application code. The TCP WebSocket test starts
plain Uvicorn on an ephemeral localhost port and uses `websockets` for the handshake, ordered snapshot,
authentication and a threaded incoming verdict. It requires no broker or database. Local timing is a
local test only; it does not establish LinuxONE performance. No PostgreSQL tests or Node harness run
in Phase A. The currently installed Starlette emits one httpx TestClient deprecation warning; httpx2
is intentionally not added to the approved dependencies.
