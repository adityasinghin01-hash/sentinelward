# SentinelWard API (for the screens)

One origin, port 8000 (through the SSH tunnel). JSON in and out; times are UTC epoch ms. Missing
values are `null`, never 0. Typed schemas: `/docs`.

**Auth.** `POST /api/session` sets the `sw_session` cookie (HttpOnly, SameSite=Lax). Every route
except `/api/health`, `/api/session` and `/api/ward/preview` needs that cookie,
`Authorization: Bearer <token>` or `?token=<token>`. Browser writes and `/ws` must come from the same
origin. Roles (screen name = server name): `nurse`, `doctor`, `it`, `biomedical` = biomed,
`operator` = admin. Who did something always comes from the session; names in bodies are ignored.

**Errors.** `{"detail": "..."}` with 401 (no/expired session), 403 (role or origin), 404 (unknown
bed/alert/device/action/record), 409 (state conflict, e.g. no open alert), 422 (invalid body, or a
body ID that disagrees with the URL), 503 (no briefing yet).

**Receipts.** Buttons return `{"command_id": "...", "accepted_at": 1792252807000}`. A button an agent
must carry out publishes a `ward/request` and returns **202** plus `"request_id"`; nothing changes
on the ward until the agent's own action/alert/record arrives. Local creates return 201, edits 200.

## Login, health, demo

| Request | Response |
| --- | --- |
| `POST /api/session` `{"role":"nurse"}` (or `{"username":"priya","pin":"4821"}`) | `{"token":"bZ0M…","role":"nurse","name":"Priya (Nurse)","display_name":"Priya (Nurse)"}` |
| `GET /api/health` | `{"ok":true,"mqtt_connected":true,"db_ok":true,"storage":"postgresql","durable":true,"beds_online":12,"last_message_ts":1792252807000,"invalid_messages":0,"pending_publications":0,"db_queued_rows":17}` |
| `POST /api/demo/run` (operator) `{"scenario":"emergency","speed":2}` (`start_at_s` optional, default 0) | 202 `{"command_id":"cmd_…","accepted_at":1792252807000,"accepted":true,"run_id":"run_20261017_160007"}`; publishes `demo_control` run with scenario and speed |
| `POST /api/demo/reset` (operator) `{}` | 202, same shape; publishes reset, clears run data (keeps beds, users, demo_runs) |

Scenarios: `full_ward_script`, `emergency`, `loose_sensor`, `drifting`, `replay_attack`,
`fake_flatline`, `flood`; speeds 1, 2, 5.

## Ward and beds

`GET /api/ward` → `{"received_at":1792252807000,"beds":[<bed> × 12]}`. One bed (B03 after a
TAMPERING verdict with `last_trusted_ts`; waveforms shortened here, real ones have 25 samples/s):

```json
{"bed_id":"B03","device_id":"MON-03","patient":{"initials":"S.T.","age":72,"sex":"F"},
 "verdict":"TAMPERING","priority":"medium","trust_score":20.0,"is_trusted":false,"connected":true,
 "isolated":false,"reason":"","requested_action":"Check patient at bedside","acknowledged":false,
 "last_updated_at":1792252805000,
 "vitals":{"hr":66.0,"spo2":97.0,"systolic":null,"diastolic":null},
 "waveform":{"ecg":[0.3,0.3],"ppg":[0.3,0.3]},
 "last_trusted":{"captured_at":1792252800000,"vitals":{"hr":66.0,"spo2":97.0,"systolic":null,"diastolic":null},
                 "waveform":{"ecg":[0.3,0.3],"ppg":[0.3,0.3]}},
 "display":"last_trusted","offline_since":null,"manual":null,"last_bedside_check":null,
 "assignment":{"clinician_id":"staff:priya","staff_id":"staff:priya","status":"assigned","ts":null,"by":null},
 "nurse_call":null}
```

- `display`: `live` (trusted), `last_trusted` (frozen at the newest trusted values), `offline` (no
  vitals for 5 s; `offline_since` = last arrival), `empty` (no monitor has sent data this run).
  `vitals` is never null once a bed has sent data.
- A bed with no verdict yet shows `verdict:null`, `priority:"none"`, `trust_score:0`,
  `is_trusted:false`, `requested_action:"None"` and `reason:"No monitor connected yet"` (with
  `display:"empty"`) or `"Waiting for the first check (about 10 s)"` (data arriving, first window
  not full). Never-seen beds have `vitals:null`, `last_updated_at:null`, `connected:false`.
- An `UNSURE` verdict's reasons name the check that held it back, e.g. `"Body-match check: ECG rate
  109 bpm differs from pulse rate 135 bpm"`; inconclusive checks come first, then waiting ones.
- Absent waveform channels are `[]`. `manual` (`{reading_id,bed_id,ts,by,hr,spo2,sys,dia,rr,notes}`)
  is separate from `vitals`.

| Request | Response |
| --- | --- |
| `GET /api/ward/preview` (public) | `{"received_at":…,"beds":[<bed> × 4]}` B01–B04 without `patient`, `manual`, `last_bedside_check`, `assignment`, `nurse_call` |
| `GET /api/beds/B03` | `<bed>` plus `"scores":{"M1":<score msg>,…}`, `"recent_verdicts":[<verdict msg> × ≤10]`, `"device":{"online":true,"isolated":false,"isolated_since":null,"last_seen_ts":1792252805000}`, `"open_alerts":[<alert msg>]`, `"monitor_alarm":{"code":"VTACH","priority":"high"}` (the alarm on the newest vitals, `null` when none) |
| `GET /api/beds/B03/history?minutes=30` (1–1440) | `{"bed_id":"B03","points":[{"ts":1792252800000,"hr":0,"spo2":null,"rr":14,"sys":null,"dia":null,"map":null,"abp_mean":null,"verdict":"NORMAL","trusted":true}, …]}` one per second, oldest first |
| `POST /api/beds/B05/acknowledge` (nurse, doctor) `{"type":"acknowledge_alert","bedId":"B05"}` | 202 receipt + `request_id`; `ack_alert` for the bed's highest-priority, newest open alert; 409 if none |
| `POST /api/beds/B05/bedside-check` (nurse, doctor) `{"type":"confirm_bedside","bedId":"B05","status":"patient_ok"}` (`result` also accepted) | 201 receipt; publishes `bedside_check` and a `bedside_check` action by `staff:<name>` |
| `POST /api/beds/B05/manual-reading` (nurse, doctor) `{"type":"record_manual_reading","bedId":"B05","heartRate":70,"spo2":97,"notes":"radial"}` (also `hr`, `sys`, `dia`, `rr`; ≥1 value) | 201 receipt; stored, shown as `manual`, publishes a `manual_reading` action |
| `POST /api/beds/B05/call-nurse` (nurse, doctor) `{"type":"call_bedside_nurse","bedId":"B05","requestedBy":"ignored"}` (`urgency`: `routine`/`urgent`) | 201 receipt; stored, pushed on `/ws` as `nurse_call`; no MQTT, no Telegram |
| `POST /api/beds/B05/assignment` (nurse, doctor) `{"type":"assign_clinician","bedId":"B05","clinicianId":"doctor-rao"}` | 201 receipt; `assignment.staff_id` is set only if the ID is a configured user |
| `POST /api/beds/B05/assignment/status` (nurse, doctor) `{"type":"update_assignment","bedId":"B05","status":"on_my_way"}` | 200 receipt; statuses `assigned`, `on_my_way`, `reviewing`, `complete`; 409 without an assignment |

## Alerts, devices, actions

| Request | Response |
| --- | --- |
| `GET /api/alerts?status=open` | `[{"v":1,"type":"alert","alert_id":"al_1","ts":…,"bed_id":"B05","verdict":"EMERGENCY","priority":"high","text":"Check","to":["staff:priya"],"ladder_step":1,"status":"open","acked_by":null,"acked_ts":null}]` one per alert_id (latest state), newest first |
| `POST /api/alerts/al_1/ack` (nurse, doctor) `{}` | 202 receipt + `request_id` (`ack_alert`) |
| `POST /api/alerts/al_1/escalate` (nurse, doctor) `{"type":"escalate_alert","alertId":"al_1","bedId":"B05"}` | 202 receipt + `request_id` (`escalate_alert`) |
| `GET /api/devices` | `[{"device_id":"MON-01","bed_id":"B01","online":true,"isolated":false,"isolated_since":null,"last_seen_ts":…,"net":<latest net_features msg or null>,"senders":1,"senders_window_start":…}, …]`; `senders` is the newest non-null `net_features.senders` in the buffered 30 min (`null` when the witness never knew it) |
| `GET /api/devices/MON-07/network?minutes=10` (1–1440) | `[<net_features msg, every field kept>, …]` oldest first |
| `POST /api/devices/MON-05/isolate` (it, operator) `{"type":"isolate_device","deviceId":"MON-05","bedId":"B05"}` | 202 receipt + `request_id` (`isolate_device`); the device is isolated only when A2 reports it |
| `POST /api/fleet-hunt` (it, operator) `{"type":"fleet_hunt","model":"MX450"}` (default `all`) | 202 receipt + `request_id` (`fleet_hunt`, target = model) |
| `GET /api/actions?limit=200` (1–5000) | `{"actions":[{"id":"act_iso","occurred_at":…,"actor":"A2","action_code":"disable_client","action":"disable_client confirmed","bed_id":"B08","device_id":"MON-08","approved_by":null,"mode":"automatic","undoable":true,"references_action_id":null}]}` newest first; one entry per action_id (latest result) |
| `POST /api/actions/act_iso/undo` (it, operator) `{"type":"undo_action","bedId":"B08","originalActionId":"act_iso"}` | 202 receipt + `request_id` (`undo_action`); 409 if not undoable |

## Incidents, reports, tickets (records from agents)

`<record>` = `{"record_id":"inc_7","kind":"incident","ts":…,"by":"A3","version":2,"data":{…},
"updated_ts":…,"updated_by":"staff:sam"}`. The same record_id from an agent replaces the stored one
(including staff edits); every staff edit keeps an audit row (who, when, field, old, new).
An `{id}` may be a record_id or, as the screens send, a **bed ID**: it then means that bed's single
unresolved incident (404 if none, 409 if several). Report routes also accept an incident ID or bed ID
(the report whose `data.incident_id` is that incident).

| Request | Response |
| --- | --- |
| `GET /api/incidents`, `GET /api/incidents/B07` | `[<record>]` newest first; `<record>` |
| `GET /api/incidents/B07/evidence` | `data.evidence` or `[]` |
| `POST /api/incidents/B07/evidence` (it, operator) `{"type":"capture_evidence","bedId":"B07"}` | 201 receipt; appends `{"evidence_id":"ev_…","kind":"signal_snapshot","label":"Manual snapshot of B07","captured_at":…,"captured_by":"staff:sam","source":"manual","filename":"ev_….json","size_bytes":2312,"sha256":"<64 hex>","content":{…}}` (SHA-256 of the canonical JSON of `content`, which holds the bed, verdict, scores, latest network features and recent actions) |
| `POST /api/incidents/B07/contain` (it, operator) `{"type":"contain_incident","bedId":"B07"}` | 202 receipt + `request_id` (`contain_incident`, target = incident record_id) |
| `POST /api/incidents/B07/resolve` (it, operator) `{"type":"resolve_incident","bedId":"B07","reason":"reflashed"}` | 202 receipt + `request_id` (`resolve_incident`, note = reason) |
| `POST /api/incidents/inc_7/report/review` (it, operator) `{"type":"review_report","incidentId":"inc_7"}` | 202 receipt + `request_id` (`review_report`, target = report record_id) |
| `GET /api/reports`, `GET /api/reports/inc_7` | `[<record>]`; `<record>` |
| `PATCH /api/reports/inc_7` (it, operator) `{"type":"save_report","incidentId":"inc_7","report":{"organisation":"Demo Hospital","description":"…","factsChecked":true}}` (or `{"data":{…}}`; `POST` is an alias) | 200 receipt; fields saved into `data` with `saved_at`/`saved_by`; `incidentId`, `savedAt`, `sentAt`, `sentBy`, `status` are server-owned; 409 once sent |
| `POST /api/reports/inc_7/mark-sent` (it, operator) `{"type":"mark_report_sent","incidentId":"inc_7","sentBy":"ignored"}` | 200 receipt; `data.status="sent"`, `sent_at`, `sent_by`, plus a `mark_report_sent` action. Records that a person sent it; nothing is sent by the API |
| `GET /api/tickets?status=open` | `[<record>]` newest first |
| `POST /api/tickets` (any role) `{"type":"create_ticket","bedId":"B10","issue":"Loose clip"}` | 201 receipt (`command_id` = new ticket record_id); `data` = `{bed_id,device_id,issue,status:"open",note,created_at,created_by,source:"staff"}` |
| `PATCH /api/tickets/tk_staff_…` (biomedical, operator) `{"type":"update_ticket","ticketId":"tk_staff_…","status":"assigned","note":"on it"}` | 200 receipt; audited |

## Briefing and workload

| Request | Response |
| --- | --- |
| `GET /api/briefing?since=2026-10-17T00:00:00Z` (ISO or epoch ms) | `{"since":"2026-10-17T00:00:00.000Z","generated_by":"IBM Granite","summary":"Quiet.","incidents":1,"untrusted_beds":2,"open_tickets":0,"blind_time":[{"bed_id":"B03","minutes":0.5}],"record_id":"br_1","ts":…,"facts":{"since_ts":…,"incident_count":1,"blind_time":[…],…},"fallback_reason":null}`; 503 when A8 has published none |
| `GET /api/workload?hours=2` (1–48) | `{"nurses":[{"nurse_id":"staff:priya","nurse_name":"Priya (Nurse)","role":"nurse","alarms_last_2h":12}],"record_id":"wl_1","ts":…}` (`role` = configured user role; omitted for unknown staff IDs); `{"nurses":[]}` when no A7 record is that recent |

`summary` and `generated_by` come from the newest A8 record (`data.narrative.text` /
`.generator`); `generated_by` is `"IBM Granite"` only when the generator was Granite, otherwise the
real generator name (e.g. `"template"`). The counts are computed by the backend from its stored data
since `since`: incident records, beds that are currently untrusted, tickets not resolved/closed, and
per-bed untrusted seconds (`blind_time`, in minutes). `facts` is the A8 record's own fact set (the
numbers the summary text was written from: `since_ts`, `shift_start`, `data_from`, `incident_count`,
`incidents`, `untrusted_bed_count`, `untrusted_beds`, `open_ticket_count`, `open_tickets`, `blind_time`,
`alerts_sent`, `alerts_acknowledged`, `median_ack_s`, `false_alarms_silenced`; only keys present), or
`null`; `fallback_reason` is why the template wrote the text, when it did.

## WebSocket `/ws`

Same session (cookie, Bearer or `?token=`). On connect: 12 `bed.updated` messages, B01…B12. Then:

```json
{"type":"bed.updated","payload":<bed, same object as in GET /api/ward>}
{"type":"connection.changed","payload":{"state":"live","occurred_at":1792252807000}}
```

`bed.updated` is sent immediately for verdict, alert, action, record, bedside, manual, nurse call
and assignment changes, and for display changes (live → last_trusted → offline); live telemetry is
sent at most once per bed per second. `connection.changed` reports hub (MQTT) health: `live` or
`disconnected`. A client more than 500 messages behind loses telemetry first; past 2,000 it is closed
(code 1013). An expired session closes the socket with 1008; an unauthenticated handshake gets HTTP
403. After a reconnect, reload `GET /api/ward`.
