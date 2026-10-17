# How our parts connect (read this before your own plan): v1.1 LOCKED

Team TessNova · SentinelWard · IBM Z Datathon 2026. **Locked by Aditya Singh on 6 Oct 2026 (v1). v1.1 approved by Aditya Singh on 11 Oct 2026.** Any change must go through Aditya Singh and bump the version, so nobody's code breaks.

**What v1.1 changed (11 Oct):** nothing that existed was renamed or removed. Added: three new message topics (8 `ward/request`, 9 `ward/demo/control`, 10 `ward/record`) and two rules ("When a recording runs out", "Event log for the tests"). Search for "v1.1" to find each change.

## Rules for everyone
- **No project code before 17 Oct.** The official rules ban it and judges can see GitHub dates. Before then: learn tools on unrelated toy examples, download and explore datasets, design on paper, set up accounts.
- **The two stars of our idea are the DATA and the AI.** The AI decides; agents only carry out its decisions; people step in only for treatment, the bedside check, and sending official reports.
- **Never copy a number from an Antigravity file** without checking it in our review files.
- **SentinelWard only listens to monitors.** It never sends anything back to a monitor. Cutting off a device happens at our own message hub.
- **Key dates (Participant Guidebook, IST; updated 10 Oct, message formats unchanged):**
  - abstract by **15 Oct, midnight**
  - LinuxONE readiness session **16 Oct, 7:30–8:30 PM** (everyone, mandatory; the Hack2skill timeline says 7:15, so join at 7:15)
  - kick-off 17 Oct, 9:00 AM; the build runs to **18 Oct, 10:00 AM**; closing ceremony 10:30 AM
  - two IBM AI/ML labs must be completed before building (README v4)

## The flow in one line
Simulated bedside monitors → message hub on LinuxONE → six checks (M1–M6) → decision layer with the safety rule → agents act → screens and phone alerts → the bedside nurse confirms.

## Who owns what (final)
| Person | Owns |
|---|---|
| **Aditya Singh** (lead) | LinuxONE server · message hub · ward simulator · data pipeline · backend API + live WebSocket · database · tests and results · video and pitch |
| **Kartik** (cyber) | hub security (Mosquitto Dynamic Security) · attacker scripts · **M5** network witness · **M4** network half · agents **A2** cut-off, **A3** evidence, **A4** fleet hunt · choosing the network features we can compute ourselves |
| **Aditya Singhal** (AI) | **M1** sensor quality · **M2** real alarm · **M3** body consistency · **M4** signal half · **D** decision layer + safety rule · reviews M6 |
| **Aditya** (automation) | agent engine (allow-list, approvals, action log, undo) · **A1** alerts (with Antara) · **A5** CERT-In draft · **A6** biomed tickets · **A7** workload · **A8** shift briefing (with Antara) · A9 (design only) · **IBM Granite** writer · **M6** drift watcher · prompt-injection test (with Kartik) |
| **Antara Gupta** (screens) | the 13 web-app screens · Telegram message templates (with Aditya) · README · video visuals |

## Who hands what to whom
| From | Sends | To | Topic / address |
|---|---|---|---|
| Ward simulator (Aditya Singh) | 1 reading per bed per second | hub (everyone reads) | `ward/bed/<bed_id>/vitals` |
| Attacker (Kartik) | fake / replayed readings, floods, a second sender, slow fake drift | the same topics, like a real attacker | `ward/bed/<bed_id>/vitals` |
| Network extractor (Kartik) | network features per device every 5 s | M5, M4 | `net/device/<device_id>/features` |
| M1–M6 (owners above) | 1 score per bed per model every 5 s | decision layer | `ward/bed/<bed_id>/score/<model>` |
| Decision layer (Aditya Singhal) | 1 verdict per bed every 5 s | agents, backend, screens | `ward/bed/<bed_id>/verdict` |
| Agents (Aditya, Kartik) | every action | backend log, screens | `ward/action` |
| A1 (Aditya) | every alert and its ladder state | backend, screens | `ward/alert` |
| Nurse (Telegram or screen) | "Patient OK / NOT OK" | decision layer, backend | `ward/bed/<bed_id>/bedside` |
| Backend (Aditya Singh) | REST + live WebSocket | screens (Antara) | `/api/...` and `/ws` |
| v1.1: Backend, for a screen button | ack / escalate an alert, cut off a device, undo an action | the agent that owns it (A1 for alerts, A2 for cut-off and its undo, the owner of any other action) | `ward/request` |
| v1.1: Backend, from the Demo button | `run` or `reset` | simulator, attack script, every model, decision layer and agent (reset = clear your per-bed memory) | `ward/demo/control` |
| v1.1: Agents (A3, A5, A6, A7, A8) | incident, report, ticket, workload, briefing records | backend → screens | `ward/record` |

## The message formats (JSON, v1 + v1.1)

**Common rules for every message:**
- `"v": 1` (format version).
- `"type"` (which message).
- Times are **Unix epoch milliseconds, UTC** (`ts`), and all machines sync their clocks (NTP).
- IDs: beds `B01`–`B12`, devices `MON-01`–`MON-12`, models `M1`–`M6`, agents `A1`–`A9`, people `staff:<name>`.
- Missing value = `null`, **never 0**, because 0 is a real value (a flatline).
- MQTT QoS 0 for `vitals`; QoS 1 for everything else. `verdict` is **retained**, so a new screen gets the latest verdict at once.

### 1. Reading: `ward/bed/<bed_id>/vitals` (1 per bed per second)
```json
{
  "v": 1, "type": "vitals",
  "bed_id": "B03", "device_id": "MON-03",
  "seq": 18452,
  "ts": 1792252800000,
  "fs": 125,
  "ecg": [0.12, 0.15, "... 125 numbers, mV"],
  "ppg": [512.0, 515.5, "... 125 numbers, a.u."],
  "abp": [92.1, 93.4, "... 125 numbers, mmHg, or null if no arterial line"],
  "hr": 82, "spo2": 97, "rr": 16,
  "nibp": {"sys": 118, "dia": 72, "map": 87, "ts": 1792252790000},
  "monitor_alarm": {"code": "VTACH", "priority": "high"}
}
```
- `seq` goes up by 1 per message per device (used by M4 to spot replays).
- `nibp` is `null` except in the message right after a new cuff reading.
- `monitor_alarm` is `null` unless the (simulated) monitor raised an alarm. M2 uses it as its trigger.
- Codes follow the 2015 challenge: `ASYSTOLE`, `BRADY`, `TACHY`, `VTACH`, `VFIB`.

### 2. Score: `ward/bed/<bed_id>/score/<model>` (each model, every 5 s)
```json
{
  "v": 1, "type": "score",
  "bed_id": "B03", "model": "M3", "model_version": "m3-2026-10-17a",
  "window_start": 1792252795000, "window_s": 10,
  "score": 0.91,
  "label": "body_mismatch",
  "reason": "Pulse arrives 480 ms after the heartbeat; this patient's usual is 205 ms",
  "extra": {}
}
```
- `score` runs 0–1, where **higher = more suspicious** for that model's question.
- **What each model's score means:**

  | Model | Score means |
  |---|---|
  | M1 | sensor unusable |
  | M2 | real emergency |
  | M3 | body mismatch |
  | M4 | replay |
  | M5 | network attack |
  | M6 | drift |
- `reason` is at most 120 characters, in plain words.
- `extra` holds model-specific numbers, e.g. M6 `{"gap_mmhg": 12.0}`, M1 `{"channel": "ppg"}`.
- Windows start on multiples of 5 s, so all six scores for a bed line up.

### 3. Verdict: `ward/bed/<bed_id>/verdict` (decision layer, every 5 s, retained)
```json
{
  "v": 1, "type": "verdict",
  "bed_id": "B07", "ts": 1792252800500, "window_start": 1792252795000,
  "verdict": "TAMPERING",
  "priority": "medium",
  "confidence": 0.88,
  "trust": 0.12,
  "last_trusted_ts": 1792252620000,
  "reasons": ["Same 10 seconds seen 4 minutes ago (replay)", "Heartbeat and pulse no longer match", "Network sender changed"],
  "scores": {"M1": 0.10, "M2": 0.05, "M3": 0.91, "M4": 0.99, "M5": 0.74, "M6": 0.02}
}
```
**Verdicts and their priority (fixed):**

| verdict | priority | who hears |
|---|---|---|
| `NORMAL` | `none` | nobody |
| `EMERGENCY` | `high` | nurse now (ladder) |
| `BOTH` | `high` | nurse now **and** device cut off (safety rule) |
| `TAMPERING` | `medium` | bedside nurse: hand-check; IT |
| `UNSURE` | `medium` | bedside nurse: hand-check |
| `DRIFTING` | `medium` | bedside nurse + biomed ticket |
| `LOOSE_SENSOR` | `low` | bedside nurse: refit; false alarm silenced |
| `DEVICE_ATTACK` | `none` (for nurses) | IT only |

**Field rules:**
- `trust` is 0–1: how sure we are this bed's data is genuine.
- `last_trusted_ts` is the newest moment we still trust (`null` if trusted now).
- At most 3 `reasons`.

### 4. Action: `ward/action` (every agent or human action)
```json
{
  "v": 1, "type": "action",
  "action_id": "act_000231", "ts": 1792252801200,
  "by": "A2", "action": "disable_client",
  "bed_id": "B07", "device_id": "MON-07",
  "detail": "Cut off MON-07 after TAMPERING (conf 0.88); session wiped",
  "undo_id": "act_000231", "undoes": null,
  "approved_by": null, "result": "ok"
}
```
- **Allowed actions (allow-list):**

  | Agent | Actions |
  |---|---|
  | A1 | `send_message`, `edit_message`, `escalate`, `record_ack` |
  | A2 | `disable_client`, `enable_client`, `set_bed_untrusted` |
  | A3 | `snapshot_files`, `hash_file`, `write_timeline` |
  | A4 | `list_devices`, `set_watch_level` |
  | A5 | `draft_report`, `start_clock` |
  | A6 | `open_ticket`, `update_ticket` |
  | A7 | `warn_workload` |
  | A8 | `write_briefing` |
  | people | `bedside_check`, `manual_reading`, `undo`, `mark_report_sent` |
- An undo is a new action with `undoes` set to the original `action_id`.

### 5. Alert: `ward/alert` (A1, on every change)
```json
{
  "v": 1, "type": "alert",
  "alert_id": "al_0042", "ts": 1792252803000,
  "bed_id": "B03", "verdict": "EMERGENCY", "priority": "high",
  "text": "Bed 3 — possible heart emergency. Go now.",
  "to": ["staff:priya"], "ladder_step": 1,
  "status": "open", "acked_by": null, "acked_ts": null
}
```
- **Ladder:** step 1 → the assigned nurse; step 2 → the next nurse; step 3 → all nurses + doctor.
- **Timer per step:** **30 s in the demo** (so judges see it), 60 s in the real design.

### 6. Bedside check: `ward/bed/<bed_id>/bedside` (nurse, from Telegram or the screen)
```json
{"v": 1, "type": "bedside_check", "bed_id": "B07", "ts": 1792252860000, "result": "patient_ok", "by": "staff:priya"}
```
`result` is `patient_ok` or `patient_not_ok`. `patient_not_ok` on any bed → A1 raises a high alert at once.

### 7. Network features: `net/device/<device_id>/features` (Kartik's extractor, every 5 s)
```json
{
  "v": 1, "type": "net_features",
  "device_id": "MON-07", "window_start": 1792252795000, "window_s": 5,
  "msgs_per_s": 1.0, "bytes_per_s": 3100, "iat_mean_ms": 1000, "iat_std_ms": 12,
  "payload_mean": 3100, "payload_std": 40, "senders": 1, "connects_per_s": 0,
  "malformed": 0, "seq_gaps": 0, "seq_repeats": 0, "stale_ms": 140
}
```
Kartik may add fields after downloading CICIoMT2024 (that's his feature-subset task); adding fields is allowed in v1, renaming or removing is not.

### 8. Request: `ward/request` (v1.1; backend, when someone presses a screen button that an agent must carry out)
```json
{"v": 1, "type": "request", "request_id": "req_000012", "ts": 1792252805000, "by": "staff:priya",
 "action": "ack_alert", "target_id": "al_0042", "bed_id": "B03", "note": ""}
```
- `action` is one of:
  - `ack_alert` (target = alert_id, handled by A1);
  - `escalate_alert` (alert_id, A1);
  - `isolate_device` (device_id, A2);
  - `undo_action` (action_id, handled by the agent that made that action).
- The agent carries it out and logs its own normal `action` message, with `approved_by` = the person (`by`).
- Acks from Telegram still go straight to A1, as before.

### 9. Demo control: `ward/demo/control` (v1.1; backend, from the Demo button)
```json
{"v": 1, "type": "demo_control", "ts": 1792252800000, "cmd": "run", "run_id": "run_20261017_160000", "start_at_s": 0}
```
- `cmd`: `run` starts the 20-minute ward script (doc 12) from `start_at_s` seconds in. The simulator and the attack script both start on it, so every run is the same.
- `reset` stops everything. Every model, the decision layer and every agent clears its per-bed memory, so the next run starts clean.

### 10. Record: `ward/record` (v1.1; agents → backend → screens)
```json
{"v": 1, "type": "record", "ts": 1792252806000, "kind": "ticket", "record_id": "tk_0007", "by": "A6", "data": {"...": "any JSON object"}}
```
- `kind` → who sends it:
  - `incident` (A3, with `data.evidence` as a list);
  - `report` (A5);
  - `ticket` (A6);
  - `workload` (A7);
  - `briefing` (A8).
- Sending the same `record_id` again replaces the earlier version. The backend stores it and serves it at `/api/incidents`, `/api/reports`, `/api/tickets`, `/api/workload` and `/api/briefing`.

### When a recording runs out (v1.1 rule)
Three ward beds play 2015-challenge recordings that are only 5.5 minutes long: B03 ends at T+05:30, B04 at T+07:00 and B07 at T+14:30 of the 20-minute script.
- When a recording ends, that monitor simply **stops sending**. The simulator never loops a recording, because a loop would look like a replay attack.
- The screen shows "monitor offline since hh:mm" with the last values (safety rule 1: never blank).
- **Models and the decision layer must treat a monitor that goes silent this way as offline, not as an attack.**

### Event log for the tests (v1.1: simulator and attack script)
So the T8 test can time every reaction, the simulator and Kartik's attack script each write one JSON line per event to their own `runs/<run_id>/events.jsonl`, the moment it happens:
```json
{"run_id": "run_20261017_160000", "t_s": 600, "ts": 1792253400000, "bed_id": "B05", "event": "attack_start", "detail": "replay of B05 from T+06:00 as a second sender"}
```
- `t_s` is the number of seconds into the 20-minute script.
- Attack script events: `attack_start` and `attack_end` per attack, plus any step worth timing (for example `second_sender_on`, `flood_start`).
- Simulator events: `run_start`, `bed_join`, `monitor_alarm`, `drift_start`, `drift_full`, `drift_end`, `source_end`, `run_end`, `run_reset`.

## Backend addresses (for the screens), v1
- `GET /api/ward` returns `{"beds": [ {bed_id, device_id, patient: {initials, age, sex}, latest: {hr, spo2, bp, rr}, verdict: <verdict message>, alarm_priority} ]}`
- `GET /api/beds/<id>`, `GET /api/beds/<id>/history?minutes=30`
- `POST /api/beds/<id>/bedside-check`, `POST /api/beds/<id>/manual-reading`
- `GET /api/alerts?status=open`, `POST /api/alerts/<id>/ack`, `POST /api/alerts/<id>/escalate`
- `GET /api/devices`, `GET /api/devices/<id>/network?minutes=10`, `POST /api/devices/<id>/isolate`
- `POST /api/actions/<id>/undo`, `GET /api/actions?limit=200`
- `GET /api/incidents/<id>`, `GET /api/incidents/<id>/evidence`, `GET` / `PATCH /api/reports/<id>`, `POST /api/reports/<id>/mark-sent`
- `GET /api/tickets`, `PATCH /api/tickets/<id>`, `GET /api/briefing`, `GET /api/workload`
- `POST /api/session`, `POST /api/demo/run`, `POST /api/demo/reset`
- **Live:** `WS /ws` pushes the same JSON messages as above (`vitals` thinned to what the screens need, `verdict`, `alert`, `action`).
- **v1.1:** the buttons for ack, escalate, isolate and undo make the backend publish a `ward/request` (topic 8). The Demo button publishes `ward/demo/control` (topic 9). Records from `ward/record` (topic 10) feed the incident, report, ticket, workload and briefing addresses. Each bed has a `display` of `live`, `last_trusted` or `offline`.

## Signals and windows
Every signal is resampled to **125 readings per second** and cut into **10-second windows every 5 seconds**, the same as the IoMT-SecAlarmBench test set.

## The five safety rules every part must respect
1. A patient is never shown as blank.
2. A "tampering" verdict never cancels an emergency alert.
3. Every automatic action can be undone with one click and is logged.
4. Nothing automatic touches treatment.
5. Official reports are drafted by the agent and sent by a person.

## 24-hour checkpoints (whole team)
- **Hour 6:** one bed works end to end (reading → verdict → screen → phone alert).
- **Hour 12:** 8 beds, every verdict type, isolation works.
- **Hour 16:** feature freeze. After this only fixes, tests, video.
- **Hour 22 (8 AM, 18 Oct):** submit early; the build ends at 10 AM.

## v1.2 (17 Oct 2026, build day, approved by Aditya Singh)
- `ward/request` (topic 8) `action` also allows: `fleet_hunt` (target = device model or `all`, A4), `contain_incident`, `resolve_incident` (target = incident_id, A3), `review_report` (target = report_id, A5). Needed by the screens' buttons.
- `ward/demo/control` (topic 9) may carry extra fields `scenario` (string) and `speed` (number, 1 = real time) from the Demo screen. Parts that don't use them ignore them.
