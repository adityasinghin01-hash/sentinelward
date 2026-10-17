# Security evidence (live, IBM LinuxONE build server)

## Live security test — 15/15 PASS (2026-10-17 14:06:49 UTC, current build)
Raw: `raw/security-live-20261017T140649Z.json` (security_v2 live test against the running hub).

| # | Check | Result |
|---|---|---|
| 1 | Valid monitor can connect | PASS |
| 2 | Valid own-bed QoS1 publish accepted | PASS |
| 3 | Anonymous publish rejected | PASS |
| 4 | Wrong password rejected | PASS |
| 5 | MON-03 cannot publish to bed B05 | PASS |
| 6 | Monitor subscription rejected (monitors may only send) | PASS |
| 7 | Connected monitor kicked on disable (cut-off) | PASS |
| 8 | Disconnected monitor cannot queue a QoS0 publish | PASS |
| 9 | Disabled monitor reconnect rejected | PASS |
| 10 | Disabled monitor publish blocked | PASS |
| 11 | Session wiped, still disabled | PASS |
| 12 | Re-enabled (Undo) own-bed publish accepted | PASS |
| 13 | TLS handshake and CA/SAN verification | PASS |
| 14 | Authenticated MQTT over TLS (port 8883, TLS 1.3) | PASS |
| 15 | Plain MQTT on 8883 rejected | PASS |

## Containment audit trail (automatic cut-off + undo)
`raw/containment.jsonl`: every `disable_client` (requested → confirmed), `clean_session` and `enable_client` the agents performed through Mosquitto dynamic security, with timestamps and device IDs (no secrets in the file). The agents cut a monitor off only after 20 s of sustained tampering evidence, or at once when an emergency is also present on BOTH, and every cut-off has an Undo. Known active emergency alerts remain visible; a disconnected monitor cannot supply later alarms, so bedside monitoring is required (`agents_v2/sw_agents/agents/a2_contain.py`, `raw/wardrun-night/judgeN.txt`, B07).

## Login and API hardening (backend tests, `backend/tests/test_auth_hardening.py`)
scrypt-hashed PINs, lockout after repeated failures, session expiry, CSRF/origin checks on every write, login audit; one-click demo login can be switched off.
