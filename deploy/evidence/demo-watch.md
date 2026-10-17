# Live demo watch, 17 Oct 2026 (LinuxONE tessnovabuild)

Operator session -> `POST /api/demo/run {"scenario":"full_ward_script","speed":1,"start_at_s":270}` -> run `run_20261017_093702`.
MQTT watcher (own client ID, non-retained messages only) for 80 s on ward/bed/+/vitals, ward/bed/+/score/+, ward/bed/+/verdict.
`/api/ward` (operator token): HTTP 200, 12 beds, 3.1 ms before the run; 7.5 ms during it (11 connected).

| bed | vitals/s | score windows M1..M6 | verdicts | mean verdict interval s | verdict types |
|---|---|---|---|---|---|
| B01 | 1.00 | 16 each | 16 | 5.00 | UNSURE |
| B02 | 1.00 | 16 each | 16 | 5.00 | NORMAL, UNSURE |
| B03 | 0.75 (pack ends T+05:30) | 16 each | 16 | 5.00 | EMERGENCY, UNSURE |
| B04 | 0.99 | 16 each | 16 | 5.00 | UNSURE |
| B05 | 0.99 | 16 each | 16 | 5.00 | UNSURE |
| B06 | 0.99 | 16 each | 16 | 5.00 | NORMAL, UNSURE |
| B08 | 0.99 | 16 each | 16 | 5.00 | UNSURE |
| B09 | 0.99 | 16 each | 16 | 5.00 | LOOSE_SENSOR, UNSURE |
| B10 | 0.99 | 16 each | 16 | 5.00 | UNSURE |
| B11 | 0.99 | 16 each | 16 | 5.00 | UNSURE |
| B12 | 0.99 | 16 each | 16 | 5.00 | NORMAL, UNSURE |

B07 is not in the ward until T+09:00. Monitor alarms: B03 VTACH (high) at +31.3 s (T+05:00).
B03 verdicts: UNSURE x6, then EMERGENCY from +32.3 s to +67.3 s (8 verdicts), then UNSURE after the pack ended.
Verdict totals: UNSURE 140, NORMAL 19, LOOSE_SENSOR 9, EMERGENCY 8.

Second run `run_20261017_093908` at start_at_s=600 (T+10:00, 60 s, 10 beds incl. B07): B10 TAMPERING on all 11
verdicts (attack runner's forged arterial drift, second sender), B06 NORMAL+UNSURE, others UNSURE. Totals: UNSURE 96, TAMPERING 11, NORMAL 4.
Both runs were stopped with `POST /api/demo/reset`; simulator logged 0 invalid, 0 publish errors, lag p99 9.35 / 7.54 ms.
