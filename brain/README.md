# SentinelWard live brain

One Python process consumes the locked doc-00 v1 MQTT messages, assembles per-bed 10-second windows every 5 seconds, publishes M1–M6 score envelopes and retained verdicts. Scores increase with suspicion. Every live detector uses `M<n>-live-2026-10-17`.

The approved decision precedence is BOTH, EMERGENCY, TAMPERING, DRIFTING, LOOSE_SENSOR, DEVICE_ATTACK, UNSURE, NORMAL. Confidence and trust are **uncalibrated** heuristic numbers. Trust is `1 - max(eligible M3, M4, M5)`; no eligible integrity check gives numeric 1 but the verdict remains UNSURE. Missing data never establishes normal physiology.

M1 checks observed ECG/PPG missingness, flat lines, clipping, implausible amplitudes and high frequency/powerline energy. M2 checks observed ECG rates, QRS width and regularity against the alarm code. For VTACH with a complete preceding window it attempts the hash-verified primary research seed 20261015 and that seed's threshold, then falls back to live rules when unavailable. M4 compares normalized, non-overlapping windows only with this bed's recent history and checks sequence repeats/regressions and authenticated sender metadata. Its optional research opinion remains in `extra`; unverified channel order prevents that research path.

An alarm is recorded before duplicate rejection and preserves EMERGENCY/BOTH through its 10-second window and another 30 seconds. A bedside `patient_ok` clears prior alarm memory; `patient_not_ok` forces emergency. Silence at 3 seconds gives offline UNSURE unless emergency or independently evidenced tampering takes precedence. Display snapshots survive reset separately from inference memory. Sequence gaps and silence alone never imply attack. Sender IDs are accepted only as out-of-band authenticated metadata; the ordinary MQTT subscriber cannot identify the publisher, and payload `device_id` is not sender proof.

## Local use

From the repository root:

```sh
python3 -m venv .venv
.venv/bin/pip install -e common -e brain pytest PyYAML
.venv/bin/pytest brain/tests attacks/tests
SW_MQTT_HOST=localhost .venv/bin/sw-brain
```

Credentials: `SW_MQTT_USERNAME`, `SW_MQTT_PASSWORD`; connection: `SW_MQTT_HOST`, `SW_MQTT_PORT`, `SW_MQTT_TLS=1`, optional `SW_MQTT_CA`. No credentials are stored in source. Vitals use QoS 0; scores, bedside/control/features and verdicts use QoS 1; only verdicts are retained.

The shared `sw_brain.io` seam uses `sw_common` topics, builders, decode/validation and MQTT `Bus`. Every outgoing envelope is checked before transport; invalid messages are rejected, counted in `invalid_outgoing` and logged. Services also count rejected direct inputs in `invalid_incoming`; the underlying shared Bus counts/logs invalid MQTT input in `bus.stats()['invalid']`. The adapter retains original payload sizes, arrival clocks and the bounded safety queue, including TLS with system trust roots when no CA file is supplied.

Optional research dependencies are deliberately absent from the required environment. Artifact loaders verify hashes before deserialization. Missing torch, incompatible dependencies, missing artifacts or failed hashes produce explicit research unavailability in `extra` while the live path continues. This is advisory prototype inference, with no automatic treatment control. Server validation still requires the real broker, LinuxONE dependencies, artifact parity, 12-bed latency and memory measurements.

M3 compares observed ECG and PPG rates, then compares pulse arrival against a rolling baseline built from at least three non-overlapping windows on this bed. Its baseline excludes divergent observations. M5 computes message rate, IAT, sequence, payload and timestamp-drift features from receipts. A fresh topic-7 subset plus measured IAT extrema/drift can invoke Kartik's SHA-verified artifact; `extra.path` distinguishes `topic7_artifact` from `received_rules`. A second sender alone gives uncertainty; gaps or silence alone never establish an attack. Standard MQTT does not expose sender IDs: the server's authenticated extractor supplies topic-7 sender counts.

M6 pairs arterial samples with distinct, fresh cuff readings and learns this patient's normal gap. Two cuff readings establish the initial pressure baseline; only small consistent changes update it. Both pressures falling together does not establish drift. A cuff MAP and current arterial mean both below 65 mmHg remain an independent emergency check even when M2 is not applicable. Cuff comparisons expire after five minutes. Every ineligible model publishes `score: null`, `extra.eligible=false` and `extra.unavailable_reason`, including missing inputs, warmup, expired comparisons and detector failures. All six score envelopes are published every five seconds, and retained `verdict.scores` includes all six models with null values for ineligible models. No unknown score is replaced with zero. M6 without arterial samples in the current window and M2 without a monitor alarm in or just before the window additionally retain `extra.not_applicable=true` and an explanatory reason. NORMAL requires every applicable check to be eligible and clear, no active alarm, and an online monitor. Not-applicable checks do not block NORMAL or baseline learning; an applicable unknown check still prevents NORMAL. Null scores are ignored by trust. Numeric zero is reserved for an eligible, computed score.

`BrainService.snapshots` retains latest accepted values; `last_trusted_snapshots` stores a separate copy only after NORMAL, and `display_snapshot(bed)` selects that copy when currently untrusted. Reset preserves display copies while clearing inference memory. Alarm and bedside/control messages have reserved bounded storage when the normal receive queue fills. Older bedside/control messages cannot undo newer safety state.

The approved alarm-preservation rule takes precedence over doc-12's expected B04 LOOSE_SENSOR and B06 TAMPERING while their ASYSTOLE alarms are active: these are EMERGENCY or BOTH until bedside `patient_ok` or alarm-hold expiry. The process only publishes scores/verdicts; agent actions, isolation, undo and official report sending belong to their existing owners.

Optional artifacts share one bounded worker thread inside the same process and a 100 ms call budget. A pending or failed artifact immediately leaves the live fallback in charge; completed results are reused only for the same bed and source window. Reset discards pending result references. Baseline admissions require current usable signals and clean clinical/network/replay checks. Consecutive frames for the same alarm episode keep its original pre-onset window.

On this Mac, Python 3.14 skipped the editable-install `.pth` files because the filesystem marked them hidden. If imports fail immediately after reinstalling locally, inspect `ls -lO .venv/lib/python*/site-packages/__editable__*.pth`; clear that local flag with `chflags nohidden .venv/lib/python*/site-packages/__editable__*.pth`. This is a local venv setup step; LinuxONE uses its native Python environment.
