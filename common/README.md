# sw_common: the SentinelWard shared contract

`sw_common` is the one package every SentinelWard part imports (team TessNova, IBM Z Datathon 2026).
It holds the topic names, a builder per message type, a checker, JSON encode/decode, clock helpers
and a validated MQTT `Bus`. The message formats are in [CONTRACT.md](CONTRACT.md) (v1 + v1.1 + v1.3 optional ecg2).

- Python 3.10+. Tested on 3.12; written to run unchanged on IBM LinuxONE (s390x, big-endian),
  macOS and Google Colab. Everything is JSON text, so byte order never matters.
- Standard library only, except `paho-mqtt>=2.1` for `Bus`. `import sw_common` works even
  without paho; it is loaded the first time you use `Bus`.

## Install

```bash
pip install ./common              # from the unzipped folder
pip install -e "./common[test]"   # editable, with pytest
# Colab
!pip install -q /content/common
```

## Rules to remember

- A missing value is `null` (`None`), never `0`. Zero is a real value (a flatline).
- NaN and infinity are never allowed in a message. `validate()` reports them; `encode()` turns them into `null`.
- Times are integer Unix epoch **milliseconds**, UTC.
- IDs: beds `B01`..`B99` (the ward uses `B01`-`B12`), devices `MON-01`..`MON-99` (B03 = MON-03),
  models `M1`-`M6`, agents `A1`-`A9`, people `staff:<name>`. Exactly two digits: `B0003` and `B00` are rejected.
- Unknown extra keys are allowed (the contract may grow). `strict=True` flags them, except in `net_features`.

## API

### clock

```python
from sw_common import now_ms, window_start_for, WINDOW_MS
now_ms()                          # 1792252800123 (int)
window_start_for(1792252799999)   # 1792252795000 (start of its 5 s window)
```

### topics

```python
from sw_common import vitals_topic, score_topic, verdict_topic, bedside_topic, net_topic
vitals_topic("B03")          # "ward/bed/B03/vitals"
score_topic("B03", "M3")     # "ward/bed/B03/score/M3"
verdict_topic("B07")         # "ward/bed/B07/verdict"
bedside_topic("B07")         # "ward/bed/B07/bedside"
net_topic("MON-07")          # "net/device/MON-07/features"
```

The builders raise `ValueError` on a bad ID.

Fixed topics: `ACTION_TOPIC` (`ward/action`), `ALERT_TOPIC` (`ward/alert`), `REQUEST_TOPIC` (`ward/request`),
`DEMO_CONTROL_TOPIC` (`ward/demo/control`), `RECORD_TOPIC` (`ward/record`).

Wildcards: `VITALS_SUB`, `SCORE_SUB`, `VERDICT_SUB`, `BEDSIDE_SUB`, `NET_SUB`. Also
`SUBSCRIPTIONS` (message type → pattern) and `ALL_SUB` (every contract pattern, as a tuple).

```python
from sw_common import parse_topic, topic_for, qos_retain_for, topic_matches
parse_topic("ward/bed/B03/score/M3")   # ParsedTopic(kind='score', bed_id='B03', model='M3', device_id=None)
topic_for(verdict_msg)                 # "ward/bed/B07/verdict"
qos_retain_for("verdict")              # (1, True); "vitals" -> (0, False); everything else -> (1, False)
topic_matches("ward/bed/+/vitals", "ward/bed/B03/vitals")   # True
```

`parse_topic` returns the message type as `kind`, plus the IDs in the topic. It raises
`ValueError` for any topic that isn't in the contract.

### messages: builders

Each builder takes the JSON fields as keyword arguments, fills in `"v"` and `"type"`, and
fills `"ts"` with `now_ms()` if you leave it out. `score` and `net_features` have no `ts`.
Builders return a plain dict and don't check it; `encode()` and `Bus.publish()` do. Extra
keyword arguments become extra fields.

```python
from sw_common import (make_vitals, make_score, make_verdict, make_action, make_alert,
                       make_bedside_check, make_net_features, make_request, make_demo_control, make_record)

make_vitals(bed_id="B03", seq=18452, ecg=ecg_125, ppg=ppg_125, abp=None, hr=82, spo2=97, rr=16)
#   device_id defaults to MON-03; nibp, monitor_alarm and missing signals default to None (null)
make_score(bed_id="B03", model="M3", model_version="m3-2026-10-17a", window_start=1792252795000,
           score=0.91, label="body_mismatch", reason="Pulse arrives 480 ms late")   # window_s=10, extra={}
make_verdict(bed_id="B07", window_start=1792252795000, verdict="TAMPERING", confidence=0.88, trust=0.12,
             scores={"M3": 0.91, "M4": 0.99}, reasons=["Same 10 seconds seen 4 minutes ago (replay)"])
#   priority is filled from VERDICT_PRIORITY ("medium")
make_action(action_id="act_000231", by="A2", action="disable_client", bed_id="B07", device_id="MON-07",
            detail="Cut off MON-07", undo_id="act_000231")          # result="ok"
make_action(action_id="act_000232", by="staff:priya", action="undo", undoes="act_000231")
make_alert(alert_id="al_0042", bed_id="B03", verdict="EMERGENCY", text="Bed 3 - go now.", to=["staff:priya"])
make_bedside_check(bed_id="B07", result="patient_ok", by="staff:priya")
make_net_features(device_id="MON-07", window_start=1792252795000, msgs_per_s=1.0, bytes_per_s=3100,
                  iat_mean_ms=1000, iat_std_ms=12, payload_mean=3100, payload_std=40, senders=1,
                  connects_per_s=0, malformed=0, seq_gaps=0, seq_repeats=0, stale_ms=140,
                  retrans_per_s=0.0)                                # extra numeric fields are fine
make_request(request_id="req_000012", by="staff:priya", action="ack_alert", target_id="al_0042", bed_id="B03")
make_demo_control(cmd="run", run_id="run_20261017_160000", start_at_s=0)
make_record(kind="ticket", record_id="tk_0007", by="A6", data={"title": "MON-07 replay"})
```

### messages: validate, encode, decode

```python
from sw_common import validate, encode, decode, MessageError

validate(msg)                 # [] when valid, else e.g. ["vitals.ecg: expected 125 entries, got 124"]
validate(msg, strict=True)    # also lists unknown fields (except in net_features)

raw = encode(msg)             # compact UTF-8 JSON bytes; NaN/inf -> null; MessageError if invalid
raw = encode(msg, check=False)  # skip the check (still turns NaN/inf into null)

message, errors = decode(raw) # never raises; message is None if raw isn't a JSON object
```

`MessageError` is a `ValueError`. Its `.errors` attribute holds the full list of errors.

### messages: constants

```python
from sw_common import (VERDICT_PRIORITY, ALLOWED_ACTIONS, ALARM_CODES, MODEL_MEANING, BED_IDS,
                       device_for_bed, bed_for_device)
VERDICT_PRIORITY["TAMPERING"]        # "medium"
"disable_client" in ALLOWED_ACTIONS["A2"]   # True; people are under ALLOWED_ACTIONS["staff"]
ALARM_CODES                          # ("ASYSTOLE", "BRADY", "TACHY", "VTACH", "VFIB")
MODEL_MEANING["M4"]                  # "replay"
BED_IDS                              # ("B01", ..., "B12")
device_for_bed("B03"), bed_for_device("MON-03")   # "MON-03", "B03"
```

Also exported: `CONTRACT_VERSION`, `MESSAGE_TYPES`, `FS`, `PRIORITIES`, `ALARM_PRIORITIES`,
`MODEL_IDS`, `AGENT_IDS`, `ALERT_STATUSES`, `BEDSIDE_RESULTS`, `REQUEST_ACTIONS`,
`DEMO_COMMANDS`, `RECORD_KINDS`.

### bus

```python
from sw_common import Bus, VERDICT_SUB

def on_verdict(message: dict, topic: str) -> None:
    print(topic, message["verdict"])

bus = Bus("linuxone.local", 1883, "decision-layer-1")
# later, when the hub is locked:
# Bus("linuxone.local", 8883, "decision-layer-1", username="decision", password="...", tls_ca_file="ca.pem")
bus.subscribe(VERDICT_SUB, on_verdict)      # or a list of patterns, e.g. ALL_SUB
bus.connect(wait_s=5)                       # True if connected; retries in the background either way
bus.publish(verdict_msg)                    # topic, QoS and retain come from the message; checked first
print(bus.stats())   # {'sent':..,'queued':..,'dropped':..,'received':..,'invalid':..,'reconnects':..,'handler_errors':..}
bus.close()                                 # or use `with Bus(...) as bus:`
```

- **`publish`** raises `MessageError` if the message is invalid. It returns `False` only when
  a QoS 0 message (vitals) is dropped while disconnected; paho queues QoS 1 messages until it reconnects.
- **`subscribe`** calls `handler(message, topic)` only for valid messages whose topic matches
  the IDs and type in the body. An invalid message is counted in `invalid` and logged once
  per topic (logger `sw_common.bus`); it is never raised. An exception from a handler is
  logged and counted in `handler_errors`. All handlers for a topic receive the same dict, so
  copy it before you change it.
- **Reconnects** happen on their own with exponential backoff (`min_backoff_s`..`max_backoff_s`).
  Subscriptions are renewed after every reconnect.
- **Threading**: the network loop runs in paho's background thread (`loop_start`), and
  handlers run on that thread.
- `strict=True` makes `publish` and `subscribe` use strict validation.

## Tests

```bash
cd common
pip install -e ".[test]"
pytest                    # all offline: the Bus tests use a fake paho client
```

The optional live test runs against a real broker, such as Mosquitto:

```bash
MQTT_TEST_HOST=127.0.0.1 MQTT_TEST_PORT=1883 pytest tests/test_bus_live.py
# optional: MQTT_TEST_USERNAME, MQTT_TEST_PASSWORD, MQTT_TEST_CA_FILE
```

`test_validate_vitals_under_1ms` checks that the median time to validate one vitals message
stays under 1 ms.
