# SentinelWard demonstration attacks

This package runs the doc-12 ward schedule through the shared `sw_brain.io` seam, backed by `sw_common.Bus`, topics, builders and decode/validation. It is one process with a separate MQTT connection. The legitimate monitor publisher continues. Invalid output is rejected before transport, counted in `AttackService.invalid_outgoing` and logged without recording a successful attack start. Rejected direct inputs are counted in `invalid_incoming`; shared Bus statistics count invalid MQTT messages.

`attacks/schedule.yaml` records the documented timings and explicitly identifies finite implementation defaults. B05 replays the captured B05 stream from T+06:00 at T+10:00 and stops at the T+15:30 Undo time. B06 starts fake flatline at T+16:00 and ends at script stop. B07 starts a flood, then a forged loop of its own older signal at T+13:45 and stops at its source end T+14:30. B10 starts forged arterial drift at T+06:00, ramps 0 to +15 mmHg over seven minutes, and holds until script stop. B11 starts an own-broker flood at T+12:00. B12 sends exact copies of its current readings for exactly T+17:00 through T+17:20. B08 drift belongs to the simulator.

B11's external port-scan phase is **not implemented** and produces `scan_unavailable`; it generates only bounded MQTT traffic to the configured broker. B11 defaults to 10 seconds of exact current-frame copies at at most 50 messages/s and 500 messages. B07 defaults to eight seconds of exact copies at 50/s, then one forged message/s until source end; its total is also capped at 500. Each forgery copies this bed's actual frame from 60 seconds before the current source frame, including older numerics and alarm state, but claims the current sequence and timestamp. Cuff timestamps shift by the same interval, preserving their relative age. This masks the coming VFIB without changing the legitimate publisher; conflicting content at the same sequence/time is independent M4 evidence even without sender identity. There is no catch-up burst after a paused or late scheduler tick. Missing current or historical sources produce `attack_unavailable`, never invented samples.

All published readings retain the full doc-00 shape: 125 ECG and PPG samples or explicit missing data and original bed/device IDs. Sequence/timestamp stay original except for B07's paced forgeries described above. B05 replays original samples and metadata; flatline changes ECG to actual zeros and adds ASYSTOLE while retaining the pulse; drift changes observed ABP samples only. A bounded five-second canonical-payload hash cache ignores this connection's echoed frames. It cannot authenticate other senders: captured frames are valid **observed** frames, and the configured broker ACLs must establish their provenance.

Doc-12 verdicts are expectations, not outcomes guaranteed by this runner. Exact fresh copies alone provide transport evidence: B11's flood supports DEVICE_ATTACK, while B12's paced second sender supplies weak UNSURE evidence and a bedside check. B07's changed content supports TAMPERING; a real VFIB alarm then requires BOTH. A forged ASYSTOLE on B06 can produce EMERGENCY/BOTH because the user's approved safety override preserves every monitor alarm. The same override takes precedence over doc-12's false-alarm suppression on B04. Actual input evidence, model outputs and bedside confirmation determine verdicts.

## Run

From the repository root, with the local test environment:

```sh
.venv/bin/pip install -e common -e brain -e attacks pytest
.venv/bin/pytest brain/tests attacks/tests
.venv/bin/sw-attacks --check-schedule
SW_ATTACK_MQTT_HOST=localhost SW_ATTACK_MQTT_USERNAME=lab-attacker .venv/bin/sw-attacks
```

Set `SW_ATTACK_MQTT_PASSWORD` separately in the environment. `SW_ATTACK_MQTT_HOST`, `PORT`, `USERNAME`, `PASSWORD`, `TLS` and `CA` override the shared seam's `SW_MQTT_*` values only inside this process. Set `SW_ATTACK_CLIENT_ID` for a unique connection ID; default is `sw-attacks`. Use separate broker-approved lab credentials to establish a distinct sender. Payload `device_id` is only a claim, not authentication.

The runner subscribes while idle and captures bounded original prehistory. `ward/demo/control` `run` anchors script time at `cmd.ts - start_at_s * 1000`; `reset` interrupts active attacks, flushes their end events, clears captures and stops publishing. Repeated and stale controls are ignored. Source timestamps are second-aligned, so replay selects the nearest real source frame on that grid, at most 500 ms from the control-relative source instant. It never loops a completed recording.

## Seeks and events

Seeking into B05's replay or B07's paced masking attack requires actual prehistory (B07 also needs its current source). Supply `--fixtures /path/original.jsonl` with either raw original vitals objects or source-relative entries:

```json
{"t_s":360,"message":{"v":1,"type":"vitals","bed_id":"B05","device_id":"MON-05","seq":360,"ts":360000,"fs":125,"ecg":["125 original numbers"],"ppg":["125 original numbers"],"abp":null,"hr":75,"spo2":98,"rr":16,"nibp":null,"monitor_alarm":null}}
```

The abbreviated sample arrays above illustrate the format; the loader requires the actual 125 numbers. Source-relative fixtures keep samples and sequence unchanged and rebase source/cuff timestamps to this run's epoch grid. Missing source frames produce unavailable events, including when a real recording has ended or been isolated.

Events are flushed at actual transitions to `attacks/runs/<run_id>/events.jsonl`, or `$SW_RUNS/<run_id>/events.jsonl` / `--runs-dir`. Each line has exactly `run_id,t_s,ts,bed_id,event,detail`. `t_s` includes seeks, and `ts` is epoch milliseconds at the transition. A successful publish precedes `attack_start`; failed publishes never report a successful start. Started attacks get paired ends on schedule, reset, process exit or run replacement. Events also identify `second_sender_on`, `flood_start`, `scan_unavailable`, and `attack_unavailable`. The simulator's event log is separate.

Broker-free tests cover the full virtual 1200-second schedule, source integrity, exact B12 duration, seeks and missing history, finite pressure slopes, flood limits, publish failures, reset/control ordering, and event keys/times. Actual Mosquitto ACLs, authenticated sender visibility, agent cut-off/Undo, and LinuxONE performance still require server checks.
