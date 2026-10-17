# Full 20-minute ward script, agents ON

## Final runs F1–F3 on build f7fef1c (17 Oct 2026)

Three back-to-back full ward runs on the LinuxONE build server, build `f7fef1c` (services restarted 21:36 IST, includes the B11 fix), agents on, network witness on, speed 1, same sampler and four human steps as runs 3 and 4 (Tom acks B03 05:50, Priya "patient OK" B05 11:30, Sam undoes B05's cut-off 15:30, nurse "patient OK" B12 18:00; every step returned 201/202 in all three runs). Every sampled API call returned 200 (except `/api/briefing` 503 before the first briefing exists). Agents bus: 0 invalid, 0 dropped, 0 handler errors. Raw outputs: `raw/wardrun-final/timeline_verdictsF*.txt`, `raw/wardrun-final/metricsF*.txt`.

| Run | Sim run id (UTC start) | T0 (epoch ms) |
|---|---|---|
| F1 | `run_20261017_161029` (16:10:29) | 1792253431000 |
| F2 | `run_20261017_163227` (16:32:27) | 1792254749000 |
| F3 | `run_20261017_165711` (16:57:11) | 1792256233000 |

| Bed | Pass check (spec 12) | F1 | F2 | F3 |
|---|---|---|---|---|
| B01 | NORMAL all run, no alert | PASS (0 non-NORMAL, 0 alerts) | PASS | PASS |
| B02 | no false alert | PASS (UNSURE blips 04:24, 05:09, 09:24–09:34; 0 alerts) | PASS (blips 04:26, 05:06–05:16, 09:21–09:36, 18:36–18:46; 0 alerts) | PASS (blips 05:07–05:17, 09:22–09:32, 18:37–18:47; 0 alerts) |
| B03 | EMERGENCY ≤ 10 s, ladder, ack | PASS 05:04, step 2, acked 05:49 | PASS 05:01, step 2, acked 05:48 | PASS 05:02, step 2, acked 05:49 |
| B04 | false asystole (alarm never suppressed) | PASS EMERGENCY 06:34 | PASS 06:31 | PASS 06:32 |
| B05 | TAMPERING, cut-off, nurse OK, Undo | PASS 09:59, cut 10:20, Undo 15:29, NORMAL 16:59 | PASS 10:01, cut 10:22, Undo 15:29, NORMAL 17:06 | PASS 10:02, cut 10:23, Undo 15:29, NORMAL 17:02 |
| B06 | faked flatline caught | PASS BOTH 15:59, cut 16:00 | PASS BOTH 16:01, cut 16:02 | PASS BOTH 16:02, cut 16:03 |
| B07 | BOTH, alert never cancelled, cut off | PASS BOTH 14:04, cut 14:05 | PASS BOTH 14:01, cut 14:02 | PASS BOTH 14:02, cut 14:03 |
| B08 | DRIFTING ≤ 30 s after cuff, ticket, NORMAL | PASS 11:09, NORMAL 16:14 | PASS 11:06, NORMAL 16:11 | PASS 11:07, NORMAL 16:12 |
| B09 | EMERGENCY by 08:36, never DRIFTING | PASS 07:54 | PASS 07:51 | PASS 07:52 |
| B10 | TAMPERING, not DRIFTING | PASS 05:59, cut 06:20 | PASS 06:01, cut 06:22 | PASS 06:02, cut 06:23 |
| B11 | DEVICE_ATTACK, IT only, no cut-off | PASS 12:04 | PASS 12:01 | PASS 12:02 |
| B12 | weak second sender → UNSURE → nurse OK | PASS UNSURE 17:04 ("Multiple publishers observed"), page 17:29, NORMAL 17:59 | **FAIL** (not shown) | **FAIL** (not shown) |
| **Beds** | | **12/12** | **11/12** | **11/12** |

| Measure | F1 | F2 | F3 | Median |
|---|---|---|---|---|
| Time-to-safe B05 (untrusted + nurse told + cut off) | 21.2 s | 23.2 s | 24.1 s | **23.2 s** |
| Time-to-safe B06 | 1.2 s | 3.1 s | 4.2 s | **3.1 s** |
| Time-to-safe B07 | 21.2 s | 18.2 s | 19.2 s | **19.2 s** |
| Time-to-safe B10 | 21.2 s | 23.2 s | 24.2 s | **23.2 s** |
| Nurse alerts (12 beds, 20 min) | 11 | 11 | 11 | 11 |
| B11 UNSURE hand-check pages (was 3 in runs 3 and 4) | 0 | 1 (05:21) | 1 (06:02) | 1 |
| Telegram sent / edited / failed | 22 / 26 / 0 | 22 / 25 / 0 | 22 / 25 / 0 | |
| A8 briefing by IBM Granite (fact-checked) | yes (19:49) | yes (19:49) | yes (19:48) | |

Time-to-safe uses the scripted attack start (B05 09:58.8, B06 15:58.8, B07 13:43.8, B10 05:58.8) as in run 4. Telegram counts: F1 from the agents journal (sendMessage/editMessageText ok lines during the run), F2 and F3 from the agents status counters before and after the run (the journal gives the same numbers). B11 was marked untrusted (no cut-off, no nurse alert for the attack) in all three runs, as in runs 3 and 4.

**Where the fails are.** B12 in F2 and F3: the attack sender ran 17:00–17:20 in both runs (`sw-attacks` events `attack_start`/`attack_end` for B12 at t 1020/1040 s), but the timeline shows `16:06-18:21 NORMAL` (F2) and `16:07-18:17 NORMAL` (F3). The B12 poll at 17:29 shows M4 0.13 with 2 (F2) and 1 (F3) duplicate frames, against 4 duplicates and M4 0.6 in F1, and `senders: 0, sender_identity_available: False` in all three runs: the replay check had no per-sender count, so only the duplicate-copy count could surface this attack and it depends on timing. This is the known, accepted B12 limit.

**B11 pages.** The new build cut B11's false UNSURE pages from 3 per run to 0, 1, 1. The two left: F2 `04:56-05:21 UNSURE Body-match check: ECG rate 64 bpm differs from pulse rate 42 bpm` (page 05:21); F3 `05:37-06:02 UNSURE Body-match check: ECG rate 63 bpm differs from pulse rate 85 bpm` (page 06:02). Both closed on their own.

## Ward run 4 (history, 17 Oct 14:49 UTC, build before f7fef1c)

*History only: superseded by F1–F3 above. Do not quote these numbers as current.*

Build after the hub-log fix (`fea3a03`) and before the B11 fix. Same sampler and human steps. Beds 11/12 PASS: B12 NOT SHOWN (no UNSURE at 17:00). B11: DEVICE_ATTACK 12:04, but 3 UNSURE hand-check pages (06:09, 10:44, 16:14). Time-to-safe B05 26.4 s, B06 1.2 s, B07 21.2 s, B10 21.2 s. 13 nurse alerts. Briefing by IBM Granite (19:48). Telegram counts were not recorded for this run.

## Ward run 3 (history, build before the hub-log fix)

*History only: superseded by F1–F3 above. The B12 "re-run pending" below was done in run 4 and F1–F3 (B12 seen in 1 of 3 final runs).*

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
