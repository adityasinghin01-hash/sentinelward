# SentinelWard security v2 — 17 October 2026

Fresh implementation; no source from the old `security/` directory was read or reused.
This controls our own MQTT hub. It never sends commands to patient monitors or treatment equipment.
Contract: doc00 v1.2 (the v1.2 addendum is inside the file named v1.1 LOCKED), doc02, doc12.

## Identity and ACL policy

Every permission defaults to deny, including delivery through old subscriptions.
Unsubscribe is allowed so clients can release subscriptions. No anonymous group exists.
Each subscriber gets both `subscribePattern` and `publishClientReceive` permissions.
The monitor role has only one publish permission and its username is bound to the same MQTT client ID.
Service usernames have no client-ID restriction because the extractor uses separate receive/publish connections.

| Username / role | Publish to hub | Subscribe and receive |
|---|---|---|
| MON-01 … MON-12 / monitor-NN | Only `ward/bed/BNN/vitals` for that device | Nothing |
| simulator | Nothing; a control connection only | `ward/demo/control` |
| brain | `ward/bed/+/score/+`, `ward/bed/+/verdict` | vitals, net features, bedside, demo control |
| backend | `ward/request`, `ward/demo/control`, `ward/action`, `ward/bed/+/bedside` | The ten contract topic filters, never `#` or `$CONTROL` |
| agents | `ward/action`, `ward/alert`, `ward/record`, `ward/bed/+/bedside` | requests, verdicts, bedside, M3/M5 scores, demo control, actions, alerts |
| attacks (deliberate test authority) | Vitals for B01–B12 only | vitals and demo control |
| extractor | `net/device/+/features` | vitals and demo control |
| admin | `$CONTROL/dynamic-security/v1` | Its `/response` topic only |

No ordinary service can write verdicts except brain, features except extractor, or dynsec commands.
The agents role matches the deployed profile: research M6 disabled. Enabling M6 requires a separately reviewed ACL extension.

The simulator currently multiplexes all beds on one connection. The supplied launch adapter replaces
its bus factory with one control Bus and twelve lazy per-device Buses; common and simulator are unmodified.
Do not run `python -m sw_sim` directly after lockdown: its control account cannot publish vitals.
Scale tests beyond B12 need separate identities/ACLs; they are deliberately outside this ward's allowlist.

## Server installation and recovery

Run between demos after syncing this directory and the changed backend auth.py to `/home/linux1/sw/app`.
The existing deployment script is not changed; do not run deployments concurrently with provisioning.
Requires the existing four units (`sw-api`, `sw-brain`, `sw-sim`, `sw-attacks`), installed agent dependencies
if `sw-agents` exists, openssl, mosquitto clients, systemd and sudo. No network server access was available during development.

```bash
cd /home/linux1/sw/app
/home/linux1/sw/.venv/bin/python -m pip install --no-deps --no-build-isolation -e ./security_v2
sudo /home/linux1/sw/.venv/bin/python security_v2/scripts/setup.py --server-ip 148.100.112.19
sudo /home/linux1/sw/.venv/bin/python security_v2/scripts/verify.py
```

Setup defaults to `/usr/lib/s390x-linux-gnu/mosquitto_dynamic_security.so`; `--plugin` overrides it.
`--log-path` defaults to `/var/log/mosquitto/mosquitto.log`. `--app`, `--venv`, `--service-user`, `--state`
are available for a different installation. TLS listens on IPv4 8883; cleartext 1883 binds only 127.0.0.1.
No firewall rule is opened. Only allow 8883 through the server firewall when off-box testing is intended;
never expose 1883. The CA certificate must be installed explicitly on off-box clients; never disable verification.
The server certificate SAN contains 148.100.112.19, 127.0.0.1 and localhost. Certificates expire after 365 days.

Setup generates 288-bit random passwords, plus per-user salted Mosquitto PBKDF2 hashes, offline.
No password is placed in process arguments, stdout, evidence or checked-in files.

| Runtime path | Owner / mode | Purpose |
|---|---|---|
| `/var/lib/sentinelward-security-v2/` | root / 0700 | First backup, master credentials, CA signing key, operation status and lock |
| `/var/lib/mosquitto/sw-security-v2/` | mosquitto / 0750 | Writable dynsec state, server cert and 0600 server key; broker cannot read CA key |
| `/home/linux1/sw/security-v2/` | linux1 / 0700 | Private service configuration; public CA copy inside |
| `…/env/{backend,simulator,brain,attacks,agents,extractor}.env` | linux1 / 0600 | Unique credentials, exact consumer env names |
| `…/devices.json` | linux1 / 0600 | Only twelve monitor passwords, for simulator/session cleanup |
| `…/admin.conf` | linux1 / 0600 | mosquitto_ctrl options: TLS localhost:8883, CA, admin username/password |
| `/home/linux1/sw/agents-data/containment.jsonl` | linux1 / 0600 | A2 requested/confirmed/failed changes, without passwords |

All env files include `SW_MQTT_USER/PASS` compatibility aliases. Exact consumed names are:
backend/simulator `MQTT_HOST/PORT/USER/PASS`; brain `SW_MQTT_HOST/PORT/USERNAME/PASSWORD/TLS`;
attacks `SW_ATTACK_MQTT_HOST/PORT/USERNAME/PASSWORD/TLS`; agents `SENTINEL_MQTT_HOST/PORT/USERNAME/PASSWORD/TLS/CLIENT_ID`;
extractor `SW_MQTT_HOST/PORT/USERNAME/PASSWORD` and `SW_MOSQUITTO_LOG`.
Backend and simulator support loopback here; their existing constructors do not accept TLS env settings.
Use common Bus with `tls_ca_file` for new off-box monitor clients.

Setup adds `90-security-v2.conf` systemd drop-ins, loaded after existing env files, preserving database,
pack and Telegram settings. It changes simulator/agent entrypoints to the supplied adapters and adds `sw-net`.
`sw-net` uses `SupplementaryGroups=adm` to read Ubuntu logs without changing user memberships.
If the log isn't readable by adm, configure a narrowly scoped read ACL plus logrotate's matching ACL;
unavailable log-derived features are honestly null until access is fixed. No extra `log_dest file` is added.

Rollback is independent of MQTT credentials and works even when Mosquitto cannot start:

```bash
cd /home/linux1/sw/app
sudo /home/linux1/sw/.venv/bin/python security_v2/scripts/rollback.py
```

The first snapshot keeps original site/drop-in/unit contents, modes, owners and prior service activity.
Rollback stops producers, restores that snapshot, removes newly created overrides, reloads systemd,
restarts the original hub, and starts the previously active services. Repeating rollback is safe.
The original hub permits anonymous **loopback** access; rollback intentionally restores that demo policy.
Root backups and generated keys remain private for recovery, not deleted or rotated.

Before switching the hub, setup arms a separate systemd rollback timer for 180 seconds. Exceptions
trigger immediate restore. A killed setup process releases its lock, allowing the timer to restore.
The timer is cancelled only after admin auth, all service-account connections, and service startup checks.
Rerunning an active setup verifies admin access and preserves passwords and disabled devices.
A completed rollback can be followed by setup again using the same generated credentials.
This cannot guarantee recovery from disk failure, a broken Python environment, broken systemd, or manual
changes to unmanaged broker includes; the root snapshot remains the manual recovery source.
`sw-net` is enabled at boot; rollback restores its prior enablement state.
Containment survives process restarts and demo resets; use IT undo before rerunning a contained bed.

## A2: real containment and undo

The supplied `run_agents.py` executes `python -m sw_agents` from the fresh `agents_v2/`
package. The module name is centralized in `sw_sec.launch.AGENTS_MODULE`; arguments and
hub-issued `SW_MQTT_HOST/PORT/USER/PASS` plus containment paths are inherited through env.
Containment integration must be verified after the fresh agents are merged.
Setup installs that entrypoint only if the agent unit exists. If agents are installed later, rollback
and rerun setup between demos so the original-service snapshot and new unit are consistent.

**A2 needs no sudo rule.** Setup provides `/home/linux1/sw/security-v2/admin.conf` as linux1:0600,
`SW_DYNSEC_OPTIONS` pointing to it, `SW_MONITOR_CREDENTIALS` pointing to the 0600 devices file,
and `SW_CONTAIN_AUDIT=/home/linux1/sw/agents-data/containment.jsonl`. The existing agent sandbox
allows that audit directory; ProtectHome=read-only still permits reading private credentials.
NoNewPrivileges stays enabled. mosquitto_ctrl must be on the service PATH.
The dynsec API grants broad administrator authority: this file must never be passed to ordinary
monitor, attack, backend or off-box clients. All current services run as linux1, so Unix isolation
between those processes is an honest limit; separate OS users are needed for that boundary.

For a maintenance-window manual check (run as linux1):

```bash
cd /home/linux1/sw/app
export SW_DYNSEC_OPTIONS=/home/linux1/sw/security-v2/admin.conf
export SW_CONTAIN_AUDIT=/home/linux1/sw/agents-data/containment.jsonl
/home/linux1/sw/.venv/bin/python security_v2/scripts/contain.py list
/home/linux1/sw/.venv/bin/python security_v2/scripts/contain.py disable_client MON-03 --dry-run
/home/linux1/sw/.venv/bin/python security_v2/scripts/contain.py disable_client MON-03
/home/linux1/sw/.venv/bin/python security_v2/scripts/contain.py enable_client MON-03
```

The helper uses subprocess argument lists, strict ASCII MON-01…MON-12 validation, bounded timeouts,
and broker identity/state confirmation. list queries only our inventory. Dry-run audits intent without
calling the broker. disableClient kicks connected clients; re-enable is an explicit operation.

Clean-session recovery first disables the device and removes its sole monitor role. While the role
is absent, it temporarily enables authentication, connects with MQTT CleanSession=1, then disables
again **before** restoring the role. An interrupted cleanup leaves either a disabled device or a
roleless device with no publish/subscribe/receive rights. It never claims success without confirmation.
If interrupted while roleless, rerun the helper's clean_session through the A2 adapter or repair via a
private admin session before IT undo; do not simply enable a roleless account and assume it can send.

`attacks` is an intentionally privileged, separate test sender. Disabling MON-05 does **not** disable
that account's ability to forge B05 traffic. For a real stolen-device-password scenario, use MON-05's
identity; for the scripted second-sender demonstration, the backend's untrusted projection freezes
trusted values while the test sender remains present. Disable/remove the attacks account outside
explicit red-team demos. This code does not claim containment of every writer to a bed topic.

## Feature measurements

The extractor receives raw vitals via paho so malformed messages are counted before common rejects
them. It publishes all thirteen contract fields for each device every five seconds through common
Bus with strict validation. Windows align to UTC epoch multiples of 5000 ms. Online count/mean/M2
statistics avoid storing waveforms; only three windows/device and at most 1024 sender IDs/window remain.
Sequence high-water marks span windows; repeats include backwards sequence numbers. Validated run/reset controls clear sequence/timestamp baselines; duplicate/stale controls do not.
An unannounced physical-device sequence reset is still measured as a replay indicator.

Rates are received MQTT messages/payload bytes, not packets or wire/TLS bytes. Interarrival times use
receiver timestamps and include the prior arrival across a window boundary. Standard deviations are
population deviations. `stale_ms` is the age of the most recently received valid payload timestamp at
window end. Empty observed windows have measured zero traffic; absent timing/payload/sequence data is
null. Startup or lost subscription coverage produces null receive metrics instead of fabricated zeros.

Broker PUBLISH logs supply MQTT client IDs for `senders`; payload device_id is never sender evidence.
A client ID is still credential-bound only for monitors; it is not a cryptographic physical-device ID.
`connects_per_s` counts authenticated MON-NN connection events. Unknown-user auth failures are counted
internally as unattributed events, not assigned to a claimed device or treated as received payloads.
Missing/unreadable/backlogged logs mean null sender/connect rates. A rotated/truncated log invalidates
the partial window; sender-set overflow produces null rather than a made-up exact count. Log tailing handles rename/truncate;
no PCAP, physical sender attribution, calibrated M5 model or OS/network flood protection is claimed.

## Server acceptance and evidence

The live test is separate and requires `SW_SECURITY_LIVE=1`. Stop producers first: MON-03 probe
connections intentionally use the device's bound ID and would kick a live simulator connection.
For clean evidence and no test data in patient projections, stop all five application units first.

```bash
cd /home/linux1/sw/app
sudo systemctl stop sw-api sw-brain sw-sim sw-attacks sw-agents
SW_SECURITY_LIVE=1 /home/linux1/sw/.venv/bin/python security_v2/scripts/live_test.py --tls-host 148.100.112.19
sudo systemctl start sw-api sw-brain sw-sim sw-attacks sw-agents sw-net
```

Omit sw-agents from these commands if it is not installed. Always run the restart command even when
the live test fails. The script prints a PASS/FAIL table and writes timestamped Markdown/JSON to
`security_v2/evidence/`, without secrets. It establishes positive connectivity/publish baselines,
checks explicit MQTT v5 rejection codes for anonymous/wrong-password/cross-bed/subscribe/disabled
clients, verifies cleanup and re-enable in a finally block, validates the TLS certificate chain/SAN,
authenticates over TLS, and checks that raw MQTT on 8883 is rejected. A timeout is never counted as
proof of rejection. An already-disabled MON-03 is preserved and reported as a failed precondition.
`--tls-host 127.0.0.1` is available if the external IP cannot hairpin; run an off-box TLS check as well.
Run verify.py after the live test, then the team's actual demo-run/bedside/undo smoke checks.

## App login

Only backend/sw_api/auth.py and backend tests change. Existing one-click `/api/session` role login
continues with `SW_DEMO_ROLE_LOGIN` default on. Existing username/PIN clients remain compatible when
no real-account file is configured; PINs are hashed in the auth store, not compared as plaintext.

Provision real credentials for the identities already defined in users.yaml:

```bash
cd /home/linux1/sw/app
/home/linux1/sw/.venv/bin/python security_v2/scripts/account.py priya --file /home/linux1/sw/security-v2/accounts.json
```

Repeat for other users who need password login. Add these lines to a **private** backend EnvironmentFile
loaded after the generated backend.env, then restart sw-api (never put passwords into shell arguments):

```dotenv
SW_AUTH_ACCOUNTS_FILE=/home/linux1/sw/security-v2/accounts.json
SW_AUTH_AUDIT_FILE=/home/linux1/sw/security-v2/auth-audit.jsonl
SW_DEMO_ROLE_LOGIN=1
```

Use a 95-auth.conf drop-in with `[Service]` and
`EnvironmentFile=/home/linux1/sw/security-v2/auth.env`; create auth.env as linux1:0600 with the above
nonsecret settings, then `sudo systemctl daemon-reload` and `sudo systemctl restart sw-api`.
Set SW_DEMO_ROLE_LOGIN=0 for password-only operation. With an account file, unprovisioned identities
cannot use their old demo PIN. The private JSON maps usernames to `scrypt$32768$8$1$<salt hex>$<hash hex>`;
16 random salt bytes/user, 32-byte derived key, hashlib.scrypt, fixed resource parameters, constant-time
comparison. Account/audit files must be owned by the API user and exactly 0600; symlinks are refused.

POST `/api/login` accepts `{"username":"priya","password":"…"}`; `/api/session` also accepts the real
password in its existing `pin` field. POST `/api/session/logout` revokes the server session and deletes
the cookie. Both explicit Bearer and query credentials for that token then fail, including open WS
auth rechecks. Auth-owned routes are installed through the app's existing write-origin middleware on
its first mutation, because app.py/model edits were excluded; they appear in OpenAPI after that call.

Five failures lock the account for five monotonic-clock minutes, including correct-password attempts.
Unknown names share one bounded lockout bucket. Successful login resets failures. Sessions expire after
30 idle minutes and the absolute SW_SESSION_TTL_S cap (default eight hours); activity never extends the
absolute cap. WS timer checks do not count as activity. Restart revokes sessions and resets lockouts;
multiple independent API workers would need a shared session/lockout store, which is not provided.

All writes use existing origin middleware: reject mismatched/opaque Origin, cross-site fetch metadata,
and no-Origin simple/form requests. Same-origin browser requests pass. Headerless CLI requests need
JSON, explicit Bearer, or X-CSRF-Token equal to the session token; no-Origin JSON preserves existing API
tests and scripts. JSON cannot be sent by cross-site HTML forms. Keep backend and frontend same-origin;
do not add permissive credentialed CORS. Host/proxy configuration remains the deployment's responsibility.
Auth audits login success/failure/lockout/logout to the logger and optional private JSONL; no passwords,
session tokens or full request bodies are logged. HTTP access logging of query tokens is an existing risk;
prefer cookies or Bearer, and keep the API behind the SSH tunnel or HTTPS.

## Threat model and limits

| Threat | Control and remaining limit |
|---|---|
| Fake readings / second sender | Unique passwords and own-bed ACLs stop unauthorized writers and cross-bed spoofing. A valid device password can still forge its own readings. Deliberate attacks account is exempt for demonstrations. |
| Replay | Sequence gaps/repeats and payload age are measured for M4/M5; ACL/TLS alone do not prove freshness or reject replay. Payload timestamps/seq are sender-controlled. |
| Flood | Auth, 1 MiB packet cap, 10k queued-message cap and bounded extractor state reduce impact. No per-client rate limiter, upstream DDoS protection or disk quota is provided. Verbose logs need logrotate/free-space monitoring. |
| Slow drift | Transport controls cannot distinguish physiological changes from forged plausible values. Signal/network witnesses and human bedside checks remain necessary. |
| Stolen monitor password | Limited to that bed, bound client ID, hub disable/kick and session purge, audited re-enable. Rotate credentials after compromise; an undo is not a password rotation. |
| Network interception | CA-verified TLS off box; local plaintext is restricted to loopback. Local privileged processes remain trusted. |
| Admin / service compromise | Ordinary MQTT roles cannot control dynsec; admin options are private. Shared linux1 Unix identity is not process isolation; root or a compromised same-user service can read secrets. |
| App login abuse / CSRF | Salted scrypt, lockout, idle/absolute limits, logout revocation, same-origin/JSON checks and audit. Demo role login deliberately bypasses passwords while enabled. No MFA/distributed lockout/store, clinical identity proofing or production certification. |

No claims of Secure Execution, Crypto Express, pervasive or post-quantum encryption, medical-device
security certification, packet-level measurements, or clinical detection performance are made.

## Local validation

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ./common -e ./backend -e ./security_v2 pytest httpx
.venv/bin/python -m pytest -c backend/pyproject.toml backend/tests security_v2/tests -q
```

Unit tests need no broker: real file snapshots and feature calculations, fake subprocess/log inputs,
ASGI API requests and injectable clocks. PostgreSQL tests require SW_TEST_PG and skip without it.
An isolated local broker check on the developer machine is supplementary; LinuxONE's Mosquitto 2.0.18,
systemd transactions, permissions/AppArmor, the installed agents and the live ward must be checked there.

Implementation references (upstream, version-pinned where relevant):
[Mosquitto 2.0.18 dynsec protocol](https://github.com/eclipse-mosquitto/mosquitto/blob/v2.0.18/plugins/dynamic-security/README.md),
[2.0.18 password format](https://github.com/eclipse-mosquitto/mosquitto/blob/v2.0.18/src/password_mosq.c),
[2.0.18 client state serialization](https://github.com/eclipse-mosquitto/mosquitto/blob/v2.0.18/plugins/dynamic-security/clients.c),
[Dynamic Security guide](https://mosquitto.org/documentation/dynamic-security/).
