# SentinelWard message contract

**Version: v1 + v1.1 additions (request, demo_control, record)**

v1 is locked. v1.1 adds three message types and three topics; every message still carries `"v": 1`.
`sw_common.validate()` checks exactly these rules. The section at the end lists how the checker
reads the points this contract doesn't spell out.

## Rules for every message

- `"v": 1` and `"type"` are always present.
- Times are Unix epoch milliseconds, UTC, as integers (`"ts"`, `"window_start"`, `"last_trusted_ts"`,
  `"acked_ts"`, nibp `"ts"`).
- IDs: beds `"B01"`–`"B12"`, devices `"MON-01"`–`"MON-12"` (bed B03 = device MON-03), models `"M1"`–`"M6"`,
  agents `"A1"`–`"A9"`, people `"staff:<name>"`.
- A missing value is `null`, never `0`. Zero is a real value (a flatline). NaN and infinity are never allowed
  in a message.
- MQTT: QoS 0 for vitals; QoS 1 for everything else. Verdict messages are published retained; nothing else is
  retained.

## Topics

| Topic | Message | Rate |
|---|---|---|
| `ward/bed/<bed_id>/vitals` | vitals | 1 per bed per second |
| `ward/bed/<bed_id>/score/<model>` | score | each model every 5 s |
| `ward/bed/<bed_id>/verdict` | verdict | every 5 s, retained |
| `ward/action` | action | |
| `ward/alert` | alert | |
| `ward/bed/<bed_id>/bedside` | bedside_check | |
| `net/device/<device_id>/features` | net_features | every 5 s |
| `ward/request` (v1.1) | request | |
| `ward/demo/control` (v1.1) | demo_control | |
| `ward/record` (v1.1) | record | |

## 1) vitals

```json
{"v": 1, "type": "vitals", "bed_id": "B03", "device_id": "MON-03", "seq": 18452, "ts": 1792252800000, "fs": 125,
 "ecg": [125 numbers, mV], "ppg": [125 numbers, a.u.], "abp": [125 numbers, mmHg] or null if no arterial line,
 "hr": 82, "spo2": 97, "rr": 16, "nibp": {"sys": 118, "dia": 72, "map": 87, "ts": 1792252790000},
 "monitor_alarm": {"code": "VTACH", "priority": "high"}}
```

- `fs` is 125. `ecg`, `ppg` and `abp` are each null or a list of exactly `fs` entries; an entry is a finite
  number or null.
- `seq` is an integer that goes up by 1 per message per device.
- `hr`, `spo2`, `rr`: integer or null. `nibp`: null except in the message right after a new cuff reading; when
  present, all four keys.
- `monitor_alarm`: null, or `code` in ASYSTOLE, BRADY, TACHY, VTACH, VFIB with `priority` high, medium or low.

## 2) score

```json
{"v": 1, "type": "score", "bed_id": "B03", "model": "M3", "model_version": "m3-2026-10-17a",
 "window_start": 1792252795000, "window_s": 10, "score": 0.91, "label": "body_mismatch",
 "reason": "Pulse arrives 480 ms after the heartbeat; this patient's usual is 205 ms", "extra": {}}
```

- `score` is 0–1, higher = more suspicious. Meaning per model: M1 sensor unusable, M2 real emergency,
  M3 body mismatch, M4 replay, M5 network attack, M6 drift.
- `reason`: at most 120 characters. `extra`: an object. `window_start`: a multiple of 5000.

## 3) verdict

```json
{"v": 1, "type": "verdict", "bed_id": "B07", "ts": 1792252800500, "window_start": 1792252795000,
 "verdict": "TAMPERING", "priority": "medium", "confidence": 0.88, "trust": 0.12, "last_trusted_ts": 1792252620000,
 "reasons": ["Same 10 seconds seen 4 minutes ago (replay)", "Heartbeat and pulse no longer match", "Network sender changed"],
 "scores": {"M1": 0.10, "M2": 0.05, "M3": 0.91, "M4": 0.99, "M5": 0.74, "M6": 0.02}}
```

- Fixed verdict → priority: NORMAL→none, EMERGENCY→high, BOTH→high, TAMPERING→medium, UNSURE→medium,
  DRIFTING→medium, LOOSE_SENSOR→low, DEVICE_ATTACK→none. A different priority is an error.
- `confidence` and `trust`: 0–1. `last_trusted_ts`: integer or null. `reasons`: at most 3 strings.
  `scores`: keys from M1–M6, values 0–1 (some models may be missing).

## 4) action

```json
{"v": 1, "type": "action", "action_id": "act_000231", "ts": 1792252801200, "by": "A2", "action": "disable_client",
 "bed_id": "B07", "device_id": "MON-07", "detail": "Cut off MON-07 after TAMPERING (conf 0.88); session wiped",
 "undo_id": "act_000231", "undoes": null, "approved_by": null, "result": "ok"}
```

Allow-list. An action not allowed for its `by` is an error.

| by | allowed actions |
|---|---|
| A1 | send_message, edit_message, escalate, record_ack |
| A2 | disable_client, enable_client, set_bed_untrusted |
| A3 | snapshot_files, hash_file, write_timeline |
| A4 | list_devices, set_watch_level |
| A5 | draft_report, start_clock |
| A6 | open_ticket, update_ticket |
| A7 | warn_workload |
| A8 | write_briefing |
| people (`staff:<name>`) | bedside_check, manual_reading, undo, mark_report_sent |

- An undo is a new action whose `undoes` is the original `action_id`. `bed_id`, `device_id`, `undo_id`, `undoes`,
  `approved_by` may be null.

## 5) alert

```json
{"v": 1, "type": "alert", "alert_id": "al_0042", "ts": 1792252803000, "bed_id": "B03", "verdict": "EMERGENCY",
 "priority": "high", "text": "Bed 3 — possible heart emergency. Go now.", "to": ["staff:priya"], "ladder_step": 1,
 "status": "open", "acked_by": null, "acked_ts": null}
```

- `ladder_step` 1–3. `status`: open, acked, escalated or closed.

## 6) bedside_check

```json
{"v": 1, "type": "bedside_check", "bed_id": "B07", "ts": 1792252860000, "result": "patient_ok", "by": "staff:priya"}
```

- `result`: patient_ok or patient_not_ok.

## 7) net_features

```json
{"v": 1, "type": "net_features", "device_id": "MON-07", "window_start": 1792252795000, "window_s": 5,
 "msgs_per_s": 1.0, "bytes_per_s": 3100, "iat_mean_ms": 1000, "iat_std_ms": 12, "payload_mean": 3100,
 "payload_std": 40, "senders": 1, "connects_per_s": 0, "malformed": 0, "seq_gaps": 0, "seq_repeats": 0,
 "stale_ms": 140}
```

- The owner may ADD numeric fields later; extra fields are always allowed here.

## 8) request (v1.1)

A button pressed on a screen that an agent must carry out.

```json
{"v": 1, "type": "request", "request_id": "req_000012", "ts": 1792252805000, "by": "staff:priya",
 "action": "ack_alert", "target_id": "al_0042", "bed_id": "B03", "note": ""}
```

- `action`: ack_alert (target = alert_id), escalate_alert (alert_id), isolate_device (device_id),
  undo_action (action_id). `bed_id` may be null.

## 9) demo_control (v1.1)

```json
{"v": 1, "type": "demo_control", "ts": 1792252800000, "cmd": "run", "run_id": "run_20261017_160000", "start_at_s": 0}
```

- `cmd`: run or reset. `start_at_s`: integer ≥ 0 (seconds into the 20-minute ward script to start from).

## 10) record (v1.1)

A ticket, report, incident, briefing or workload record from an agent.

```json
{"v": 1, "type": "record", "ts": 1792252806000, "kind": "ticket", "record_id": "tk_0007", "by": "A6",
 "data": {"any": "JSON object"}}
```

- `kind`: ticket, report, incident, briefing or workload. The same `record_id` sent again replaces the earlier
  version.

---

## How `sw_common` reads the open points (team decisions, 2026-10-17)

These were agreed when the package was built. They don't change any rule above.

1. **IDs** have exactly two digits: beds `B01`–`B99`, devices `MON-01`–`MON-99`. `B00`, `B3` and `B0003` are
   rejected. The ward uses B01–B12 (`BED_IDS`), but the checker validates the format, so B13–B99 also pass.
   When a message carries both `bed_id` and `device_id` (vitals, action), they must belong together.
2. **`hr`, `spo2`, `rr`** accept an integer or a finite float, or null. `seq` and every timestamp must be integers.
3. **Every field shown is required.** A missing value is sent as `null`, not left out.
4. **Unknown extra keys** are allowed by default. `strict=True` lists them as errors, except in `net_features`.
   NaN and infinity are errors anywhere, including in extra keys, `score.extra` and `record.data`.
5. **`window_start` must be a multiple of 5000** in score, verdict and net_features. They all use the same 5 s windows.
6. **An `undo` action** must have a non-null `undoes`. A9 has no allowed actions, so any action `by: "A9"` is an error.
7. **Not checked** because the contract doesn't define them: the format of action_id, alert_id, request_id,
   record_id, run_id, model_version, label and result (any non-empty string passes); vital-sign ranges;
   `window_s` beyond being a positive integer; the length of verdict reasons (the 120-character limit is for
   `score.reason`). Also not checked: alert priority against the verdict, `to` entries beyond being
   non-empty strings, and request targets other than `isolate_device`.
8. **net_features numbers** may be null when a value is missing. `nibp` sys/dia/map may be null; `nibp.ts` must be an integer.
9. **`bedside_check.by`** must be `staff:<name>`. `request.by` and `record.by` may be an agent or a person.
10. **`seq` going up by 1** can't be seen in a single message. The checker only requires an integer ≥ 0.
11. **On the wire**, a message whose topic doesn't match its type or IDs is treated as invalid by `Bus`.
    A zero-length payload is MQTT's signal for clearing a retained message; it is ignored, not counted as invalid.
