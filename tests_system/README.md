# Server system checks

The CLIs do not use pytest, import model internals, query PostgreSQL, alter broker security or stop
other people's services. They use HTTP `/api/...`, MQTT, the documented simulator CLI and the two
`runs/<run_id>/events.jsonl` streams. H6 additionally checks `/ws`. Python 3.12+ on LinuxONE uses the
existing `~/sw/.venv`: sw_common/paho-mqtt, httpx, PyYAML and (T10) system psutil. Analysis uses only
the standard library. The stdlib WebSocket receiver avoids adding a test-only server dependency.

On the server, after deployment, with the ward idle:

```bash
cd ~/sw/app
set -a
. ~/sw/.env
set +a
~/sw/.venv/bin/python tests_system/smoke_h6.py
~/sw/.venv/bin/python tests_system/t8_ward.py
~/sw/.venv/bin/python tests_system/t10_resources.py --scale
```

The environment loader above assumes the existing `.env` uses shell-compatible assignments.
Do not echo it or enable shell tracing. MQTT credentials come from `MQTT_HOST`, `MQTT_PORT`,
`MQTT_USER`, `MQTT_PASS`. Admin PIN login is read from backend/users.yaml (override `--users`);
session tokens/PINs are not saved. Override `--api`, `--packs`, `--sim-runs` and `--attack-runs`
when the server paths differ. Backend origin defaults to http://127.0.0.1:8000 (no `/api` suffix).

H6 waits for an idle MQTT interval, starts only B03 at T+04:30 with a unique MQTT client ID, watches
75 seconds, and SIGTERMs only its own child. It does not send a global reset. The source ends at
T+05:30, so the correct expectation is **60 ±2 vitals**, rather than the prompt's 75 ±2. It reports
wire-size median rather than treating “about 3 KB” as an exact size contract. Score rows show each
model's measured window-end delay and count; a null score envelope does not prove a usable detector.
All Aditya Singh hops must PASS for exit 0. Inference/A1 can be MISSING, but a backend emergency
check that cannot execute because its upstream verdict is missing remains NOT RUN and yields
nonzero exit. Phone delivery always needs a person: its row is NOT RUN and does not affect H6 exit.

T8 defaults to **three real-time 20-minute runs**, waiting for run_end and then another 30 seconds.
`--runs 1` is useful for debugging; the three-run summary remains NOT RUN until three are supplied.
T10 samples are captured automatically during T8 run 1, including `top -b -n 1` at or just after
T+10:00 (actual timestamp is recorded). No bedside acknowledgements, “Patient OK”, or B05 undo are
fabricated: the people/agents prescribed in doc 12 must perform them during each run. Missing steps
are reported with script-time fallback where doc 07 permits it. If interrupted, T8 resets only a
run it started, after verifying the latest observed run control still has that ID. Other services
remain running. A failed setup/early stop prevents automatic repetition.

Raw evidence goes to `tests_system/out/smoke_<time>/` and `out/t8_<run_id>/`: `bus.jsonl` contains
actual payload bytes as decoded text, sizes, receipt epoch and monotonic clocks, retain/QoS flags,
validation errors and decoded messages, including rejected messages. `ward_polls.jsonl` records
HTTP receipt time, measured request duration, response status and JSON. Event logs are copied into
the output folder. QoS duplicates and retained startup verdicts do not count as new detections.
The Bus raw callback is instrumented like the existing brain adapter; shared validation still runs.

Rebuild tables without connecting to anything:

```bash
~/sw/.venv/bin/python tests_system/smoke_h6.py --analyze tests_system/out/smoke_<time>
~/sw/.venv/bin/python tests_system/results_table.py tests_system/out/t8_<run1> tests_system/out/t8_<run2> tests_system/out/t8_<run3>
~/sw/.venv/bin/python tests_system/t10_resources.py --analyze tests_system/out/t8_<run1>
```

Reports are JSON, Markdown and CSV in **tests_system/results/**, with per-run copies alongside
raw logs. The T8 aggregate preserves each FAIL and its exact event/message evidence, plus mean,
min and max only when all three numeric measurements exist. FAIL measurements remain in the
summary; no missing value is replaced with zero. Markdown/CSV round to 3 decimals at rendering;
JSON retains precision. Generated reports/raw logs and the local venv are gitignored.

Definitions for Blind Time are written verbatim into every report, including the assumption
“nobody notices until the episode ends”. Hidden and pre-notification unmonitored components are
added as specified, even if they overlap. Poll intervals use left-hold integration at 1-second
resolution; missing coverage or a gap over 2.5 seconds makes that measurement NOT RUN. Recording
gaps are actual source_end → run_end intervals (B07's normal monitor gap continues after attack
end). B11 has zero hidden time by definition. Time-to-safe requires a successful matching-device
cut-off AND a medium/high alert addressed to staff; the later receipt defines its end.

Strict expected-verdict rows remain exactly doc 07: B04 LOOSE_SENSOR and B06 TAMPERING can therefore
FAIL under the approved brain alarm-preservation override. The separate attack detection metric
accepts BOTH as an integrity warning. B10's strict 15-second onset deadline is reported even though
the script expects network signs around T+13:00; this is called out beside its result. Actual event
and cuff times take priority; fallback rows explicitly say “script time”. Nurse alerts count distinct
alert IDs, not ladder updates. Monitor alarms include simulator events and logged forged alarm
occurrences; when the current attacker omits forged-alarm events, original B06 seq/ts alarm frames
inside its logged attack interval provide the occurrence evidence. No occurrence evidence means
NOT RUN. “Alarms stopped” is the alarm-count minus nurse-alert-count comparison, **not a claim of
verified per-alarm suppression**; it can be negative. Missed emergencies count the three real
emergencies that lack EMERGENCY or BOTH by their deadlines, including late detection; strict expected-verdict checks remain separate.

T10 scale leaves models/agents running and lists the PIDs/roles actually found; it never stops them.
It attempts the prescribed 50/100/200/500 sizes when supported. The current simulator's public limit
is 87 extra beds (B13–B99), so 100/200/500 say NOT RUN with that reason. That contract ceiling is
not a measured performance limit. Hub on-time percent uses unique received frames within the
simulator's documented 50-ms budget over N×60 expected frames (missing frames count late); publisher
on-time percent is reported separately. It stops at the first measured result under 99%. CPU is
system total plus per-process one-core percent, first observations marked warmup; memory is system
used and per-PID RSS. Delays are measured source timestamp → receipt; verdict delay uses
window_start + 10 seconds. Negative values are retained as clock/window evidence. Raw per-second
hub counts, process manifests and timing samples allow recomputation.

Offline verification from the Mac (only tests_system/ is written):

```bash
python3 -m venv tests_system/.venv
tests_system/.venv/bin/python -m pip install pytest
tests_system/.venv/bin/python -m pytest -q tests_system/tests
```

Server execution has not happened in the sandbox. Local synthetic tests and the isolated Mac
frontend build do not establish MQTT delivery, Telegram delivery, isolation/undo, model quality,
LinuxONE performance or PostgreSQL persistence. Server-only checks are currently NOT RUN.
