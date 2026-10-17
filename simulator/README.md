# sw_sim: SentinelWard ward simulator

`sw_sim` plays the 12 bed packs as 12 live bedside monitors. Each bed publishes one `vitals` message per
second to our own Mosquitto hub (`ward/bed/<bed_id>/vitals`, QoS 0), following the 20-minute ward script
in `ward_script.yaml`. It also injects B08's arterial-line drift and writes a ground-truth event log
for the T8 test.

It runs on the LinuxONE build server next to the hub (s390x, Ubuntu 24.04, Python 3.12). Attacks
(replays, fake flatlines, floods, a second sender) are **not** in this program; they come from the
teammate's attack script. It never talks to a real monitor.

## Install

```bash
sudo apt install python3-numpy python3-yaml python3-venv
python3 -m venv --system-site-packages /opt/sentinelward/venv   # sees Ubuntu's numpy
/opt/sentinelward/venv/bin/pip install --no-deps -e /opt/sentinelward/common      # sw_common (part 02)
/opt/sentinelward/venv/bin/pip install --no-deps -e /opt/sentinelward/simulator
```

`--no-deps` keeps pip from downloading a PyPI numpy over Ubuntu's. `sw_common` brings paho-mqtt 2.1.

## Commands

All commands accept `--packs DIR` (default `$SW_PACKS`, else `./packs`), `--script FILE` (default
`./ward_script.yaml`) and `--runs DIR` (default `$SW_RUNS`, else `./runs`).

```bash
# The full 20-minute ward in real time
python -m sw_sim run --packs /data/packs --script ward_script.yaml

# Jump to T+04:30 to see B03's real VT alarm 30 s later, with only two beds
python -m sw_sim run --packs /data/packs --script ward_script.yaml --start-at T+04:30 --beds B03,B04

# Build and validate every message of the whole script in a few seconds, send nothing
python -m sw_sim run --packs /data/packs --script ward_script.yaml --dry-run

# Self-test at 20x speed (ts is virtual; the run is marked "fast" in the event log)
python -m sw_sim run --packs /data/packs --script ward_script.yaml --speed 20

# Wait for the web app's Demo button on ward/demo/control
python -m sw_sim listen --packs /data/packs --script ward_script.yaml

# T10 resource test: 40 quiet extra beds for 5 minutes
python -m sw_sim scale --beds 40 --seconds 300 --packs /data/packs --script ward_script.yaml
```

`run` options: `--start-at T+mm:ss` (also `mm:ss` or plain seconds), `--speed N` (N >= 1), `--beds B03,B05`,
`--dry-run`, `--run-id ID` (default `run_YYYYMMDD_HHMMSS`, UTC). A plain `run` also obeys a `reset` on
`ward/demo/control`. A `run` command arriving there is ignored; use `listen` for that.

Exit codes: 0 means OK; 1 means some messages failed validation or publishing (see the log); 2 means a
bad argument, script or pack.

### listen and the Demo button

- `{"v":1,"type":"demo_control","cmd":"run","run_id":"run_20261017_160000","start_at_s":0}` starts a
  run. If a run is already going, it is reset first.
- `{"v":1,"type":"demo_control","cmd":"reset",...}` stops the current run before its next second
  (well under 1 s). It writes `run_reset`; the next run starts every seq counter at 1 again.
- `run_id` must match `[A-Za-z0-9][A-Za-z0-9_.-]{0,63}`, because it becomes a folder name.
  `start_at_s` must be within `0..1199`.

### scale

`scale --beds N` adds N quiet beds above the ward's range: **B13..B99 with MON-13..MON-99, at most 87**,
so the normal 2-digit IDs pass `sw_common.validate`. Each one replays a copy of one of the ward's MIMIC
packs (B01, B02, B05, B06, B11, B12), starting 61 s further into the pack for each repeat. Pack alarms are
left out so the beds stay quiet. The ward beds B01-B12 are not played.

The report goes to the console and to `runs/<scale_id>/report.json`. It gives messages sent vs
expected; messages sent on time (lag <= `lag_budget_ms`, 50 ms) in total and per second (mean and
minimum); lag p50, p99 and max; CPU seconds and % of one core; and peak RSS. Stop the six AI models (or
point them away) during T10, or they will score the extra beds.

## How timing works

- **Absolute schedule.** T+00:00 is the next whole wall-clock second plus `lead_ms` (1 s). With
  `origin = T0 - start_at`, second k is due at `origin + k*1000` ms. That is computed from integers
  each time, never by adding sleeps, so the run cannot drift over 20 minutes. The messages for second k
  are built and validated during the idle time before the deadline; at the deadline the run only
  publishes. The real clock reads wall time once and then counts with the monotonic clock, so an NTP
  step during the run cannot bend the schedule.
- **ts** is the scheduled second (epoch ms, UTC), not the moment of sending. In `--speed` above 1 and
  `--dry-run` it is virtual time `origin + k*1000`, and `run_start`/`run_end` carry `"fast": true`.
- **Send lag** = time when publish returns minus the deadline. It is logged per second in `sent.csv`;
  p50/p99/max are in `run_end`. The target is p99 < 50 ms with 12 beds.
- **--start-at.** Bed position = `pack_start_s + (T - join_s)` when T >= `join_s`. A bed is silent
  before it joins and after its pack's last full second. Example at T+04:30: B03 is at pack second 270
  and B04 at 180. Events before the start point are not written, because they did not happen in this
  run. `run_start.detail` records each bed's pack second and state, plus the drift offset, at the
  start point.
- **Pack end.** When a pack runs out (B03 at T+05:30, B04 at T+07:00, B07 at T+14:30) the monitor
  stops and `source_end` is written. A partial last second is dropped, never padded; recordings never loop.

## Message content

- Exactly 125 samples per channel per second. ECG is rounded to 3 decimals, PPG to 2, ABP to 1. A
  channel the pack doesn't have is `null`. NaN samples become `None` before validation, so the
  message is the same JSON whether or not `encode` would also have mapped them; they are sent as `null`
  and the rest of that second is sent normally.
- v1.3: when the pack has `ecg2`, every message also carries `ecg2` (125 samples, rounded like ECG, NaN as
  `null`) and `ecg_leads` (lead names from the pack json, e.g. `["II", "V"]`; VitalDB `SNUADC/ECG_V5` is sent as
  `V5`). Packs without `ecg2` send neither key, so the message is exactly the v1 message.
- hr, spo2 and rr are the pack's value for that second rounded to an integer (half up). NaN gives
  `null`, and 0 stays 0.
- `monitor_alarm` (`code`, `priority`) is set only in the message for the alarm's second
  (floor of `t_offset_s`).
- `nibp` is set only in the message for the second of a new cuff reading. Its `ts` is the exact cuff
  moment, `origin + (join_s + t_offset_s - pack_start_s) * 1000`.
- **B08 drift** applies to ABP only. Each sample at time `t = k + i/125` gets
  `15 * (t - 300) / 420` mmHg from T+05:00 to T+12:00, then 15 mmHg until T+15:00, then 0 at once.
  Cuff, HR, ECG and PPG are never touched. Check values: +8.36 at T+08:54, +13.07 at T+11:06.
- Every message passes `sw_common.validate` before it is sent. A failing message is logged with the
  reason and skipped. Its seq number is reused by the next good message, so seq has no gaps.
- **seq** is one counter per device, starting at 1 for each run and going up by 1 per sent message.

## Output files

`runs/<run_id>/` (or `runs/<run_id>_dry/` for a dry run). If the folder exists, `__2`, `__3`, ... is
added; nothing is overwritten. The `run_id` inside the files stays the one given, so T8 can join with
the attack log. Every line is written with a single `write()` to an append-only file, so readers never
see half a line. Files are fsynced when the run stops.

### events.jsonl (ground truth, same line format as the attack log)

```json
{"run_id":"run_20261017_160000","t_s":300,"ts":1792253100000,"bed_id":"B03","event":"monitor_alarm","detail":{"code":"VTACH","true_alarm":true,"priority":"high","device_id":"MON-03","pack_second":300,"t_offset_s":300.0,"in_message":true,"delivered":true}}
```

| event | bed_id | when (`t_s`) | detail |
|---|---|---|---|
| `run_start` | null | first second played | start_at_s, run_length_s, origin_ms, fast, speed, dry_run, beds{...}, drift{offset_mmHg_at_start} |
| `bed_join` | bed | the bed's first sent message (every bed, including those starting at T+00:00) | device_id, pack_second, scheduled_join_s, seq |
| `monitor_alarm` | bed | the alarm's second | code, true_alarm, priority, device_id, pack_second, t_offset_s, in_message, delivered |
| `drift_start` / `drift_full` / `drift_end` | B08 | 300 / 720 / 900 | channel, offset_mmHg, ... |
| `source_end` | bed | first second with no pack data | device_id, pack_second, messages_sent, last_seq |
| `run_end` | null | 1200 when complete; actual time (3 decimals) if stopped by a signal | reason (complete, signal, shutdown or error), messages_sent, invalid, publish_errors, lag_p50_ms, lag_p99_ms, lag_max_ms, per_bed_sent |
| `run_reset` | null | actual time (3 decimals) of the reset | same as run_end |

For scheduled events, `ts = origin_ms + t_s * 1000`, the same ms as the matching message `ts`.

### sent.csv

```
t_s,sent,max_lag_ms
0,10,1.2
```

There is one row per second played. `max_lag_ms` is empty if nothing was sent that second.

## Environment variables

| variable | default | meaning |
|---|---|---|
| `MQTT_HOST` | `localhost` | Mosquitto hub |
| `MQTT_PORT` | `1883` | hub port |
| `MQTT_USER` / `MQTT_PASS` | unset | hub login |
| `SW_PACKS` | `./packs` | bed pack folder (`<bed_id>.npz` + `<bed_id>.json`) |
| `SW_RUNS` | `./runs` | output folder |

## Run as a systemd service (listen mode)

`/etc/sentinelward/sim.env` (mode 600, it holds the hub password):

```
MQTT_HOST=localhost
MQTT_PORT=1883
MQTT_USER=sw_sim
MQTT_PASS=change-me
SW_PACKS=/data/sentinelward/packs
SW_RUNS=/data/sentinelward/runs
```

`/etc/systemd/system/sw-sim.service`:

```ini
[Unit]
Description=SentinelWard ward simulator (listen mode)
After=network-online.target mosquitto.service
Wants=mosquitto.service

[Service]
Type=simple
User=sentinel
WorkingDirectory=/opt/sentinelward/simulator
EnvironmentFile=/etc/sentinelward/sim.env
ExecStart=/opt/sentinelward/venv/bin/python -m sw_sim listen --script /opt/sentinelward/simulator/ward_script.yaml
KillSignal=SIGTERM
TimeoutStopSec=10
Restart=on-failure
RestartSec=2

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now sw-sim
journalctl -u sw-sim -f
```

SIGTERM (from `systemctl stop`) finishes the current second, writes `run_end` with reason `shutdown`,
and closes the bus.

## Tests

The tests run offline with small synthetic packs, a fake bus that records and validates every message,
and a fake clock (optionally ±20 ms jitter). No broker is needed; `sw_common` must be installed.

```bash
cd simulator && python -m pytest -q
```

They cover all ten acceptance checks: message counts, alarms, nibp, drift values, seq (including
restart after reset), `--start-at`, validation with NaN/0 handling, the event log, schedule stability
under jitter, and reset within 1 s. They also cover invalid-message skipping, publish failures, scale
IDs and the 87-bed cap, the CLI, script and pack checks, and big-endian-safe pack loading.

## Files

```
simulator/
  pyproject.toml        package sw_sim; depends on sw_common, numpy, pyyaml
  ward_script.yaml      join times, drift injector, run length (all timing lives here)
  README.md
  sw_sim/__main__.py    command line: run / listen / scale
  sw_sim/config.py      environment variables, ward script loading and checks, T+mm:ss
  sw_sim/packs.py       bed pack loader (float32 LE -> native float64), per-second slices
  sw_sim/drift.py       B08 drift offset as a pure function of T
  sw_sim/clock.py       RealClock, VirtualClock (--speed), InstantClock (--dry-run)
  sw_sim/engine.py      WardRun: absolute schedule, message building, seq, ground-truth log
  sw_sim/eventlog.py    events.jsonl and sent.csv writers
  sw_sim/listen.py      demo_control controller
  sw_sim/scale.py       T10 resource test
  tests/                pytest, offline
```
