# 12 · Ward script v1 (9 Oct 2026): the 20-minute test ward

This is the written plan for test T8 and the demo video. It's the same 20 minutes every time, so the numbers can be repeated. **On paper only:** the simulator and attack scripts that run it are built on 17–18 Oct.

Every bed below uses real recordings that were checked on 9 Oct (doc 11). Where a source still needs checking, it says **"confirm at H1"**.

## Rules for the run
- **Clock:** T+mm:ss from the moment `POST /api/demo/run` starts the simulator.
- **Messages:** one `vitals` message per bed per second (doc 00 v1), 125 numbers per signal. 2015 records (250 Hz) and VitalDB (500 Hz) are resampled; MIMIC is already 125 Hz.
- **Monitor alarms:** a 2015 bed raises `monitor_alarm` at 300 s into its record. The code comes from the record's ALARMS type: Asystole→`ASYSTOLE`, Bradycardia→`BRADY`, Tachycardia→`TACHY`, Ventricular_Tachycardia→`VTACH`, Ventricular_Flutter_Fib→`VFIB`.
- **Beds that "join" later:** a 2015 record is only 5.5 minutes, so its monitor connects partway through (a new admission). Its device is on the allowed list from the start, so connecting is not an attack.
- **Cuff:** on VitalDB beds, `nibp` is sent only when a new cuff reading arrives (the value changes).

## The 12 beds
| Bed | Patient source (checked 9 Oct) | Signals | What happens | Expected verdict |
|---|---|---|---|---|
| B01 | MIMIC p000109, piece 3346682_0014 (from 2 h in) | II, V, PLETH, RESP | Nothing. Quiet bed | `NORMAL` all 20 min |
| B02 | MIMIC p000052, piece 3533390_0011 | II, V, PLETH, RESP | Nothing. Quiet bed | `NORMAL` all 20 min |
| B03 | 2015 **v221l**: true VT (opened and read) | II, V, PLETH, ABP | Real VT at T+05:00 | `EMERGENCY` |
| B04 | 2015 **a123l**: false asystole (signals checked; confirm at H1) | ECG + PLETH + ABP | False asystole alarm at T+06:30; the pulse keeps going | `LOOSE_SENSOR` |
| B05 | MIMIC p000107, piece 3860035_0044 | II, V, PLETH | Replay attack at T+10:00 | `TAMPERING` → cut off → nurse "Patient OK" → undo |
| B06 | MIMIC patient #4 from our sample (confirm at H1) | II + PLETH | Fake flatline at T+16:00 | `TAMPERING` |
| B07 | 2015 **f543l**: true VF (signals checked; confirm at H1) | ECG + PLETH + ABP | Real VF at T+14:00 **and** an attack on its device from T+13:45 | `BOTH` |
| B08 | VitalDB **5552**, surgery minutes 231–251 (opened and read) | ECG II, PLETH, ART, cuff | Slow sensor drift injected T+05:00 → T+12:00, fixed at T+15:00 | `DRIFTING`, then back to `NORMAL` |
| B09 | VitalDB **912**, surgery minutes 38–58 (opened and read) | ECG II, PLETH, ART, cuff | Real blood-pressure fall, confirmed by the cuff | `EMERGENCY` (**never** `DRIFTING`) |
| B10 | VitalDB **4277** (screened only; confirm at H1, backup 5659) | ECG II, PLETH, ART, cuff | Slow **hacker** drift T+06:00 → T+13:00, with network signs | `TAMPERING` (not `DRIFTING`) |
| B11 | MIMIC patient #5 from our sample (confirm at H1) | II + PLETH | Network attack only (scan + flood) at T+12:00 | `DEVICE_ATTACK` (IT only) |
| B12 | MIMIC patient #6 from our sample (confirm at H1) | II + PLETH | A second sender appears briefly at T+17:00 | `UNSURE` → nurse "Patient OK" → `NORMAL` |

How to pick MIMIC patients #4–#6 at H1:
- Take the next patients in our sample that have a piece at least 1 h long with II + PLETH at the same time.
- If there aren't enough, use VitalDB ward-ready cases (2,617 listed in doc 11).
- Never put the same patient on two beds.

## Minute by minute
| T+ | Bed | Event (who triggers it) | What the system must do |
|---|---|---|---|
| 00:00 | all | Simulator starts (Aditya Singh). B04 and B07 are empty | 10 beds `NORMAL` |
| 01:30 | B04 | Monitor connects, a123l starts | `NORMAL` |
| 05:00 | B03 | v221l reaches its alarm: `VTACH` | M2 high → `EMERGENCY` within 10 s. A1 alert step 1 |
| 05:00 | B08 | Drift injector starts: the line reading creeps up 0 → +15 mmHg over 7 min, a transducer slipping about 20 cm (Aditya Singh's injector) | Nothing yet |
| 05:30 | B03 | Nobody answers step 1 | A1 escalates to step 2 (30 s timer in the demo) |
| 05:50 | B03 | Nurse 2 acknowledges on Telegram (Aditya) | Alert closed, action logged |
| 06:00 | B10 | Slow hacker drift starts, same size and shape, but sent as forged messages (Kartik) | Nothing yet |
| 06:30 | B04 | a123l reaches its alarm: `ASYSTOLE` (false: ECG artefact, pulse and pressure continue) | M1 high, M2 low → `LOOSE_SENSOR` within 10 s: "refit the ECG lead". False alarm silenced |
| 06:06 → 08:36 | B09 | 912's pressure slides. Cuff 64 at T+06:06, line under 65 from T+08:00, cuff **57** at T+08:36 | M6 sees the line **and** cuff falling together → **not drift**. `EMERGENCY` (high) by T+08:36 at the latest: "low blood pressure, confirmed by cuff" |
| ~07:00 | B09 | Heart rate briefly reads 0 (a real glitch in the recording) | Must **not** turn B09's emergency into `LOOSE_SENSOR` |
| 08:54 | B08 | Cuff reading: line ≈ 8 mmHg above the cuff | M6 score rising |
| 09:00 | B07 | Monitor connects, f543l starts | `NORMAL` |
| 10:00 | B05 | Attacker replays B05's stream from T+06:00 as a second sender (Kartik) | M4 replay + M5 two senders → `TAMPERING` by ~T+10:10 |
| ~10:15 | B05 | A2 cuts off MON-05 (`disable_client`, `set_bed_untrusted`) | Screen: grey "UNTRUSTED", **last trusted values from T+10:00 stay on screen**. A1 sends a medium alert: "hand-check bed 5". A3 saves evidence |
| 11:06 | B08 | Cuff reading: line ≈ 15 mmHg above the cuff, heart rate and pulse timing unchanged | `DRIFTING` (medium): "re-level and re-zero the transducer; take a cuff reading". A6 opens a biomed ticket |
| 11:30 | B05 | Nurse taps "Patient OK" (Antara) | Logged. Stays isolated until IT acts |
| 12:00 | B11 | Port scan + flood against MON-11 (Kartik) | M5 → `DEVICE_ATTACK`: **IT only, no nurse alert**. A4 fleet hunt, A3 evidence, A5 drafts the CERT-In report and starts the 6-hour clock |
| ~13:00 | B10 | Hacker drift now about 10 mmHg off the cuff, and the network shows forged messages | M6 drift + M5 network → `TAMPERING`, **not** `DRIFTING` |
| 13:45 | B07 | Attack on MON-07 starts: flood + second sender (Kartik) | `TAMPERING` |
| 14:00 | B07 | f543l reaches its alarm: `VFIB` (true) | **`BOTH`**: nurse alerted now (high) **and** device cut off. The tampering verdict never cancels the emergency. Last trusted values stay on screen |
| 15:00 | B08 | Injector stops (the nurse "re-zeroed") | Next cuff at T+16:12 agrees → back to `NORMAL`. Ticket stays open for biomed |
| 15:30 | B05 | IT clicks Undo on the cut-off (Kartik) | `enable_client` logged with `undoes`. B05 trusted again, `NORMAL` |
| 16:00 | B06 | Fake flatline: forged messages with a flat ECG + `ASYSTOLE`, while the real pulse keeps coming (Kartik) | M3: heart flat but pulse present = body mismatch. M5: sender changed. M2 low → `TAMPERING` (medium) + hand-check. **This is the video's "faked flatline caught" moment** |
| 17:00 | B12 | A second sender publishes 20 s of plausible values (Kartik) | Weak M4/M5 evidence → `UNSURE` → hand-check |
| 18:00 | B12 | Nurse taps "Patient OK" (Antara) | `NORMAL` |
| 19:00 | all | A8 writes the shift briefing for these 20 minutes | Briefing on screen |
| 20:00 | all | Stop. `POST /api/demo/reset` | |

## Pass checks (written down after every run)
1. **No false alerts:** B01 and B02 never leave `NORMAL`.
2. **Right verdict, on time:**
   - Every event reaches its expected verdict within 15 s.
   - Cuff-based events (B08, B09) within 30 s of the confirming cuff reading.
3. **Safety rules:**
   - B09 is never `DRIFTING`.
   - B07's emergency alert is never cancelled.
   - No bed ever goes blank (B05 and B07 keep showing last trusted values).
   - Every automatic action has an undo, and B05's undo works.
4. **Numbers for the results table (T8):**
   - Time-to-safe for B05 and B07 (attack start → isolated **and** nurse told).
   - Blind Time with and without SentinelWard.
   - Seconds from each event to its verdict.
   - Total alerts sent to nurses compared with alarms raised by the monitors.

## People during the run
- **Aditya Singh:** starts and stops the run, runs the drift injector, records the timings.
- **Kartik:** attack script (B05, B06, B07, B10, B11, B12) and the B05 undo.
- **Antara and Aditya:** play nurse 1 and nurse 2 on Telegram.
- **Aditya Singhal:** watches the six scores and the verdicts live and notes anything wrong.

Kartik's attacks should be **one script with these timings**, so every run is the same.
