# agents_v2: SentinelWard agent layer A1-A8 (fresh build, 17 Oct 2026)

One plain-Python process (`python -m sw_agents`) on the MQTT hub. Dependencies: `sw_common`, `paho-mqtt`,
`httpx` (all pure Python; nothing needs a compiler on s390x). No code from `agents/` or other branches was used.

## Layout

| File | What |
|---|---|
| `sw_agents/engine.py` | The one action path: allow-list (`sw_common.ALLOWED_ACTIONS`) → `validate` → `ward/action` → append-only `actions.jsonl` (0600). Undo routing, timers, request routing, dedupe, demo reset. |
| `sw_agents/agents/a1_alerts.py` | Alerts per the doc00 table, one alert per bed episode (edits, never duplicates), 30 s ladder, ack/escalate (screen, Telegram, bedside), IT notices. |
| `sw_agents/agents/a2_contain.py` | `set_bed_untrusted` at once + `disable_client` after `SW_A2_CONFIRM_S` (20 s) of sustained TAMPERING/DEVICE_ATTACK or at once on BOTH / a person's request, through security_v2 `Containment` (dry run without `SW_DYNSEC_OPTIONS`), undo = `enable_client`, survives restarts. |
| `sw_agents/agents/a3_evidence.py` | 10-min ring buffer per bed → `messages.jsonl`, `verdicts.jsonl`, `timeline.json` with SHA-256; incident record with `data.evidence`; contain/resolve requests. |
| `sw_agents/agents/a4_fleet.py` | `fleet_hunt` request (and automatically after a cut-off): `list_devices` with "check next" findings, undoable `set_watch_level` (60 min). |
| `sw_agents/agents/a5_report.py` | CERT-In draft + 6 h clock per incident, `missing_fields`, DPDP "from 13 May 2027". No send code exists. |
| `sw_agents/agents/a6_tickets.py` | Biomed tickets: DRIFTING, or LOOSE_SENSOR 3 episodes in 10 min per device; one ticket per open problem. |
| `sw_agents/agents/a7_workload.py` | Alerts per nurse in 2 h, `warn_workload` at ≥ 40, workload record every minute. |
| `sw_agents/agents/a8_briefing.py`, `granite.py` | Facts since 08:00 → IBM Granite (`/v1/completions`, own thread, 120 s timeout, 120 tokens, one worked example), every number and every count claim checked against the facts (a failing tail sentence is dropped, else template); published at once and rewritten in place when Granite finishes; T+19:00 text started at T+18:00. `generated_by` says which. |
| `sw_agents/telegram.py` | Bot API via httpx: one message per alert per chat, edited in place, ≤ 1 call/s, callback buttons only. INFO line per delivered send/edit (method + alert id); `sent`/`edited`/`failed`/`queued` in status.json. |
| `sw_agents/telegram_check.py` | One-off delivery check: `python -m sw_agents.telegram_check /home/linux1/sw/agents2.env` sends "SentinelWard test: delivery check" to the IT chat, prints ok/failed (no token, no chat IDs). |
| `sw_agents/service.py`, `config.py` | Bus wiring, worker/ticker/Telegram threads, status file, env settings (`deploy/agents2.env.example`). |

## Behaviour decisions (documented, not in the spec text)

- A2 never hides a real emergency: on TAMPERING the bed is marked untrusted and the nurse told to hand-check at once, but the hub cut-off waits until the attack verdict has held `SW_A2_CONFIRM_S` (20 s) of consecutive verdicts (any other verdict restarts the count). BOTH, an isolate/contain request by a person, cut off at once. So B07's real VFIB alarm still reaches the brain and becomes BOTH (high alert, then cut-off).
- UNSURE: a nurse is paged after 6 verdicts (~30 s); an UNSURE alert closes only after 4 NORMALs in a row; after it closes, the same nurse is not paged again for UNSURE on that bed for 3 min (`SW_A1_UNSURE_REPAGE_S`, logged as a note; the bed screen still shows UNSURE). Other verdicts are never held back.
- undo_id only on `set_bed_untrusted`, `disable_client`, `set_watch_level`, `open_ticket`, `record_ack`, `warn_workload` (the engine drops it on anything else).
- Medium/low alerts open after 2 consecutive verdicts (high at once). Brain warm-up (UNSURE, not offline, no score ≥ 0.5) gives no alert, only a log note. NORMAL ×2 closes medium/low and acked alerts; an unacknowledged high alert is never closed or lowered automatically.
- Ladder runs for high and medium (setting), not low. Step 2 = assigned + next nurse, step 3 = all nurses + doctor.
- `patient_ok` acknowledges the bed's open alert; `patient_not_ok` raises (or supersedes with) a high alert at once.
- Undoable: `set_bed_untrusted`/`disable_client` (one undo releases both; both are logged as undone), `set_watch_level`, `open_ticket`, `record_ack`, `warn_workload`. Not undoable by design: messages, evidence, drafts, briefings.
- After a person undoes a cut-off, A2 does not cut that device again until its bed is NORMAL.
- Demo `reset` (and `run`) clears all per-bed memory and timers and re-enables devices A2 cut off (`SW_A2_RESET_RELEASES`).

## Tests

```bash
python3.12 -m venv agents_v2/.venv
agents_v2/.venv/bin/pip install -e common -e security_v2 -e agents_v2 pytest
cd agents_v2 && .venv/bin/python -m pytest -q                       # 121 passed, 1 skipped (live)
SW_AGENTS_LIVE_MOSQUITTO=/opt/homebrew/sbin/mosquitto .venv/bin/python -m pytest -q   # 122 passed
```

Unit tests use a fake bus, fake clock, fake hub broker and fake HTTP (no network). The fixture checks after every
test that every published message passes `sw_common.validate` and no handler/timer raised. The live test starts
its own Mosquitto on a free port, runs alert → ladder → ack, TAMPERING → dry-run cut-off → incident → report,
undo via `ward/request` and a demo reset, then stops the broker. Also checked once by hand (not committed): our
message stream replayed into `backend/sw_api` `WardState` isolates and releases MON-05, shows no stale Undo, and
resolves `/incidents/B07`, its report, tickets, workload and briefing.

## Run on the server

```bash
cd /home/linux1/sw/app
/home/linux1/sw/.venv/bin/python -m pip install --no-deps --no-build-isolation -e ./agents_v2   # httpx must be present
install -m 0600 deploy/agents2.env.example /home/linux1/sw/agents2.env    # then edit
mkdir -p -m 0700 /home/linux1/sw/agents2-data /home/linux1/sw/agents-data
sudo cp deploy/systemd/sw-agents2.service /etc/systemd/system/ && sudo systemctl daemon-reload
sudo systemctl stop sw-agents; sudo systemctl enable --now sw-agents2    # the unit Conflicts= with sw-agents
journalctl -u sw-agents2 -f ; cat /home/linux1/sw/agents2-data/status.json
/home/linux1/sw/.venv/bin/python -m sw_agents.telegram_check /home/linux1/sw/agents2.env   # one test message
```

Measured on the server (17 Oct, not yet deployed; code copied to /tmp and run with the server venv):
one A8 briefing end to end through `generate()` → A8's thread → Granite 350M at 127.0.0.1:8090 took 45.1 s
(331 prompt + 120 completion tokens); the template went out at 0.0 s and the same record was rewritten
by IBM Granite. The Telegram check printed `ok: delivered to the IT chat`.

Not verified here (needs the server): s390x install, real dynsec cut-off (needs security_v2 setup's
`SW_DYNSEC_OPTIONS`/`SW_CONTAIN_AUDIT`), Telegram with a real token/chat IDs, Granite at 127.0.0.1:8090,
the hub ACL (security_v2's agents role does not list `ward/record`; that subscription is then just refused).

## Open questions

Historical B11 question below: recorded before the later cut-off-label and alert-policy fixes; it does not describe the current implementation.

1. A DEVICE_ATTACK cut-off silences that monitor; the brain then reports UNSURE "offline" and A1 sends a hand-check alert. Safe, but doc12 says B11 is "IT only".
2. The backend replaces a record when the same `record_id` arrives again. A5 updates a draft only until `review_report`, and A6 updates tickets on new episodes; either can overwrite a staff edit made in between.
3. Medium alerts escalate to the doctor after 60 s without an ack (B05 in doc12 is acked at ~80 s). Set `SW_A1_LADDER_PRIORITIES=high` if that is too noisy.
4. No 12-second waveform image on Telegram: the agents role cannot read vitals.
5. The briefing counts data from when this process started or was last reset, not from before that; the record's `data_from` says so.
