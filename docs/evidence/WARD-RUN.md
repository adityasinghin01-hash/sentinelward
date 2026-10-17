# Full 20-minute ward script, agents ON (ward run 3, final brain + agents)

Run `run_20261017_141851` on the LinuxONE build server, 17 Oct 2026 14:18:53–14:38:53 UTC, speed 1, 12 real patient recordings, the scripted attacks, and four human steps played through the API as the real staff (nurse Tom acks B03 at 05:50, nurse Priya marks B05 "patient OK" at 11:30, IT (Sam) undoes B05's cut-off at 15:30, nurse marks B12 OK at 18:00; all returned 201/202). Raw samples: `.work/wardrun3/` (every 5 s: ward, alerts, actions, health; every 30 s: each bed's six scores). 0 API errors, 0 agent errors.

| T+ | Bed | Script (docs/spec/12-ward-script.md) | What happened | Result |
|---|---|---|---|---|
| all | B01 | NORMAL all run | NORMAL 00:12–19:57, 0 nurse alerts | PASS |
| all | B02 | NORMAL all run | NORMAL except 4 short UNSURE blips (5–15 s, body-match), 0 nurse alerts | PASS (no alert) |
| 05:00 | B03 | EMERGENCY ≤ 10 s, ladder, ack | EMERGENCY 05:02 (+2 s); high alert to Priya; step 2 at 30 s; acked by Tom 05:48 | PASS |
| 06:30 | B04 | false ASYSTOLE | EMERGENCY 06:32 while the monitor alarm is held (alarms are never suppressed) | PASS (safety rule) |
| 06:06–08:36 | B09 | EMERGENCY by 08:36, never DRIFTING | EMERGENCY 07:52–19:17, one episode, low pressure confirmed by cuff; never DRIFTING | PASS |
| 10:00 | B05 | TAMPERING, cut-off, evidence, nurse OK, Undo | TAMPERING 10:02; untrusted + hand-check alert 10:07; cut off 10:23 (after 20 s of sustained evidence); nurse OK 11:28; IT Undo 15:29 (enable_client logged with `undoes`); NORMAL 17:02 | PASS (NORMAL 92 s after Undo) |
| 11:06 | B08 | DRIFTING ≤ 30 s after cuff, biomed ticket | DRIFTING 11:07 (+2 s after the 11:05 cuff); ticket opened; NORMAL 16:12 after re-zero | PASS |
| 12:00 | B11 | DEVICE_ATTACK, IT only | DEVICE_ATTACK 12:02 (flood 15.5 msg/s); IT notice, no nurse alert for the attack, no cut-off | PASS |
| ~06:00 | B10 | TAMPERING, not DRIFTING | TAMPERING 06:02 (forged drift, conflicting frame content); cut off 06:28 | PASS |
| 13:45 / 14:00 | B07 | TAMPERING, then BOTH (nurse alerted + cut off) | DEVICE_ATTACK 13:47 → TAMPERING 13:52 → **BOTH 14:02** (real VFIB); high alert, never cancelled; cut off 14:03 | PASS |
| 16:00 | B06 | faked flatline caught | BOTH 16:02 (forged ASYSTOLE alarm kept as an alarm + conflicting content); cut off 16:03; held to the end | PASS |
| 17:00 | B12 | weak second sender → UNSURE → nurse OK | no verdict change at 17:00: the network witness could not read the hub's log (file mode 0600), so it never counted senders; found after this run and fixed (log 0640, group adm; `security_v2/sw_sec/deploy.py`) | NOT SHOWN (cause fixed) |
| 19:00 | all | A8 shift briefing | written by **IBM Granite** on LinuxONE (fact-checked; template fallback not needed) | PASS |

**Results table (T8)**
- Time-to-safe (attack start → bed untrusted AND nurse told AND device cut off): B07 19.3 s, B05 24.2 s, B10 29.3 s, B06 4.3 s (emergency present → cut off at once). B11 is IT-only by design.
- Event → verdict: B03 +2 s, B04 +2 s, B05 +3 s, B06 +3 s, B07 +2 s (BOTH after VFIB), B08 +2 s after cuff, B10 +3 s, B11 +3 s.
- Nurse alerts: 13 in 20 minutes for 12 beds (B01/B02: 0). Telegram: 24 messages sent + 27 edited, 0 failed (agents status counters).
- No bed lost its values: attacked beds kept showing their last trusted numbers while cut off.

**Known gaps (honest):** B12's weak attack did not surface live (network witness blind, since fixed; re-run pending); B05 took 92 s to return to NORMAL after IT's Undo (the tampering latch waits for 30 s of clean data after the replay attack ends); B11 had 3 UNSURE hand-check pages from a clipped pulse signal.
