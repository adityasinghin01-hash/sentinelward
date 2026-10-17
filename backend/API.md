# Phase A HTTP and WebSocket API

One origin, port 8000. Times are UTC epoch milliseconds. Protected routes require the session cookie,
`Authorization: Bearer <token>` or `?token=<token>`. Errors are JSON `{ "detail": ... }` (401 missing/
expired session, 403 role/origin, 404 missing resource, 409 conflicting state, 422 invalid input).
See `/docs` for typed requests and response schemas. Phase B endpoints return 404 in this build.

| Method/path | Access | Example input → response |
| --- | --- | --- |
| POST `/api/session` | Public | `{"role":"nurse"}` or `{"username":"priya","pin":"4821"}` → `{"token":"opaque","role":"nurse","name":"Priya (Nurse)","display_name":"Priya (Nurse)"}` and HttpOnly cookie |
| GET `/api/ward` | Any session | → `{"received_at":1792252800000,"beds":[<bed> × 12]}` |
| GET `/api/ward/preview` | Public | → `{"received_at":1792252800000,"beds":[<bed> × 4]}` B01–B04 with patient/manual/bedside fields omitted |
| GET `/api/devices` | Any session | → `[{"device_id":"MON-01","bed_id":"B01","online":false,"isolated":false,"isolated_since":null,"last_seen_ts":null,"net":null}, ...]` |
| GET `/api/actions?limit=200` | Any session | → `{"actions":[<action>]}` newest first; limit 1–5000 |
| GET `/api/health` | Public | → `{"ok":true,"mqtt_connected":true,"db_ok":false,"storage":"memory","durable":false,"beds_online":0,"last_message_ts":null,"invalid_messages":0,"pending_publications":0}` |
| POST `/api/demo/run` | Operator/admin | `{"scenario":"replay_attack","speed":2,"start_at_s":0}` → 202 demo receipt; publishes demo_control |
| POST `/api/demo/reset` | Operator/admin | `{}` → 202 demo receipt; clears run data, retains config/users/sessions/demo audit |
| POST `/api/beds/B05/acknowledge` | Nurse/doctor | `{"type":"acknowledge_alert","bedId":"B05"}` → 202 request receipt; ack_alert targets highest-priority newest open alert; 409 if none |
| POST `/api/beds/B05/bedside-check` | Nurse/doctor | `{"type":"confirm_bedside","bedId":"B05","status":"patient_ok","notes":"Checked"}` or `{"result":"patient_ok"}` → 201 command receipt; publishes bedside_check and staff action |
| POST `/api/alerts/al_1/escalate` | Nurse/doctor | `{"type":"escalate_alert","alertId":"al_1","bedId":"B05"}` → 202 request receipt; escalate_alert |
| POST `/api/devices/MON-05/isolate` | IT/admin | `{"type":"isolate_device","deviceId":"MON-05","bedId":"B05"}` → 202 request receipt; isolate_device |
| POST `/api/actions/act_1/undo` | IT/admin | `{"type":"undo_action","originalActionId":"act_1","bedId":"B05"}` → 202 request receipt; undo_action; action must exist, be successful and undoable |

A command receipt is `{"command_id":"cmd_unique","accepted_at":1792252800000}`.
A request receipt additionally contains `"request_id":"req_unique"`.
A demo receipt additionally contains `"accepted":true,"run_id":"run_unique"`.
Requests do not change authoritative alert/device/action state until an agent's message arrives.
URL/body IDs must agree, including the stored bed relationship. `notes` is optional. Body-supplied
identities are ignored. Separate accepted requests receive separate IDs; no implicit idempotency key.

Demo scenario values: `full_ward_script`, `emergency`, `loose_sensor`, `drifting`, `replay_attack`,
`fake_flatline`, `flood`. Speeds: 1, 2, 5. Run defaults to full script, speed 1, offset 0. Backend passes
scenario/speed through the shared MQTT contract; the simulator/agent owns execution.

Example bed before telemetry or verdict:

```json
{
  "bed_id":"B01","device_id":"MON-01","patient":{"initials":"A.K.","age":67,"sex":"F"},
  "verdict":"UNSURE","priority":"medium","trust_score":0,"is_trusted":false,
  "connected":false,"isolated":false,"reason":"Awaiting verdict","requested_action":"Continue monitoring",
  "acknowledged":false,"last_updated_at":null,"vitals":null,"waveform":{"ecg":[],"ppg":[]},
  "last_trusted":null,"display":"offline","offline_since":null,"manual":null,"last_bedside_check":null
}
```

With telemetry, `vitals` is `{"hr":0,"spo2":null,"systolic":120,"diastolic":80}` and waveform contains
25Hz samples when available. Frozen values retain their original timestamp in
`last_trusted:{"captured_at":1792252800000,"vitals":{...},"waveform":{"ecg":[],"ppg":[]}}`.
`is_trusted` describes the current feed, and stays false for isolated, frozen, offline or awaiting-verdict
beds. The display fallback is never written into a model verdict or score. Clinical emergency verdicts
and priority remain visible during isolation. Preview uses the same shape minus sensitive fields.

Action example:

```json
{"id":"act_1","occurred_at":1792252800000,"actor":"A2","action_code":"disable_client",
 "action":"Device isolated","bed_id":"B05","device_id":"MON-05","approved_by":"staff:sam",
 "mode":"automatic","undoable":true,"references_action_id":null}
```

WS `/ws` uses the same cookie, Bearer or query token. The initial stream is twelve `bed.updated`
messages in bed order (no separate snapshot envelope). Subsequent envelopes are:

```json
{"type":"bed.updated","payload":{"bed_id":"B01","...":"the complete bed projection above"}}
{"type":"connection.changed","payload":{"state":"disconnected","occurred_at":1792252800000}}
```

The first example is abbreviated for readability; actual messages contain the complete bed object.
Connection states are `live` or `disconnected` from MQTT health. Critical bed changes bypass telemetry
coalescing. Session expiry/origin rejection uses WS policy code 1008 (unauthenticated handshakes are
HTTP 403); queue overflow uses 1013. Clients should refresh `/api/ward` after reconnect.

Deferred to Phase B: workload (`{"nurses":[]}` when absent), briefing, manual reading writes, nurse calls,
assignments, fleet hunt, incident/report/ticket routes, extra bed/history/alert/network reads,
PostgreSQL batching/warm restart/durable outbox and the Node frontend contract harness. Current frontend
fixtures and optimistic command stores remain an integration limitation until their owner connects them.
