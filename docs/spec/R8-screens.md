# Phase 8 (R8): The screens. What real ICU screens look like, and our full screen spec

TessNova · IBM Z Datathon 2026 · 6 Oct 2026 (v2) · for **Antara Gupta** (and her Codex).
Builds on R7 (`phase7-icu-reality.md`). Design rules also checked against the ui-ux-pro-max skill (WCAG 2.2 AA, dashboard and anti-pattern rules).

**Tags:** VERIFIED = read at source · REPORTED = from a secondary write-up · DESIGN = our decision.
**Endpoints and message formats are now LOCKED in doc 00 v1 (6 Oct).** Where this file and doc 00 differ, doc 00 wins.

---

## Part A. What we learned from real screens

### A1. Real central stations (what nurses already know)
| Product | What matters for us | Source | Tag |
|---|---|---|---|
| Philips IntelliVue Information Center iX | Up to **32 patients** on one central station, dual-display option. Waveforms, numbers, "Horizon Trends", review of events and trends (up to 7 days). Nurses and equipment get assigned to patients. | [PIIC iX brochure](https://images.philips.com/is/content/PhilipsConsumer/Campaigns/HC20140401_DG/Documents/Philips-IntelliVue-PIIC-iX-Brochure.pdf) | VERIFIED (read the PDF) |
| GE CARESCAPE Central Station | A "multi-viewer" of patient tiles. Each tile's **title bar turns red, yellow or cyan** and flashes by alarm priority, "easy to see from a distance". An Alarm Display Unit shows the **top 4 alarms**. **Patient names can be hidden** for privacy. The title bar can stop flashing once silenced. | [GE brochure (search text)](https://www.gehealthcare.com/content/dam/gehc/sitecore-migrated-assets/marketplace/products/carescape-central-station/documents/brochure-carescape-Central-Station-v3-JB16287XX_Oct3%20(1).pdf) | REPORTED |
| Mindray BeneVision CMS | Up to 32 devices per central station. The touch screen shows **16 patients at once**, up to 4 displays and 64 beds. A "Patient Summary" view combines vitals or ECG with alarms. 240 hours of waveform recall. | [Mindray CMS page](https://www.mindray.com/en/products/patient-monitoring/centralized-monitoring/benevision-cms) | REPORTED |
| Philips eICU (tele-ICU) dashboard | **Circles = patients**, coloured by status, so a remote team sees "who needs care now" at a glance. Driven by 100+ clinical rules. Average tele-ICU watches ~150 patients at once. | [HealthManagement](https://healthmanagement.org/c/icu/News/philips-introduces-graphical-dashboard-for-icu-management) | REPORTED |
| Masimo "Signal IQ" | A small bar under the pulse waveform shows **how confident the machine is** in the reading. When confidence is very low, a "Low Signal IQ" message flashes. | [Masimo Signal IQ whitepaper](https://professional.masimo.co.uk/siteassets/uk/documents/pdf/clinical-evidence/whitepapers/lab5318b_whitepapers_signal_iq.pdf) | REPORTED |
| Claroty Medigate (medical-device security) | IT side: an inventory of every connected device (maker, model, firmware, location), a risk score, threat detection with behaviour baselines, and policy enforcement through firewalls. | [Claroty / G-Cloud listing](https://www.applytosupply.digitalmarketplace.service.gov.uk/g-cloud-14/services/124723791800607) | REPORTED |

### A2. Alarm colour rules (international standard IEC 60601-1-8)
| Priority | Colour | Flashing | Source | Tag |
|---|---|---|---|---|
| High | **Red** | 1.4–2.8 flashes per second, 20–60% on | patents and device manuals quoting the standard | REPORTED |
| Medium | **Yellow** | 0.4–0.8 flashes per second, 20–60% on | same | REPORTED |
| Low | **Cyan** (or yellow) | steady, not flashing | GE CARESCAPE uses red/yellow/cyan | REPORTED |

### A3. Phone alerts (copy what works)
- GE-Ascom phone alerts carry the **bed, severity, status and up to a 12-second waveform snapshot**, and use staff-assignment escalation. [GE](https://www.gehealthcare.com/middle-east/products/patient-monitoring/care-ports/ge-ascom-secondary-alarm-notification-solution), REPORTED.
- **Telegram limits** ([Bot API](https://core.telegram.org/bots/api), [Bot FAQ](https://core.telegram.org/bots/faq), VERIFIED):

  | Limit | Value |
  |---|---|
  | Message text | 1–4096 characters |
  | Photo caption | 0–1024 characters |
  | Button `callback_data` | 1–64 bytes |
  | Sending rate | about 1 message per second per chat; 20 per minute in a group; about 30 per second overall |

  Buttons work through inline keyboards plus `answerCallbackQuery`, and a message can be edited after a button press.

### A4. Why this matters now (for the pitch)
- ECRI's Top 10 Health Technology Hazards for **2026** include:
  - #2 being unprepared for a "**digital darkness**" event (systems going dark),
  - #8 **cybersecurity risks from legacy medical devices**,
  - #9 **designs that push staff into unsafe workflows**.

  [ECRI 2026 list](https://home.ecri.org/blogs/ecri-events/top-10-health-technology-hazards-for-2026), REPORTED.
- Our screens must not become hazard #9. That is why the rules below exist.

---

## Part B. Our design rules (Antara: follow these on every screen)

1. **Alarm colours mean alarm only.** Red = high, yellow = medium, cyan = low, flashing as in A2. Nothing else in the app may be red, yellow or cyan: no red buttons, no yellow badges.
2. **The base UI is calm navy and blue.** It matches our team look and keeps alarms standing out.
3. **Untrusted = grey diagonal stripes**, a pattern not already used by any alarm, plus the words "UNTRUSTED", the last trusted value and how old it is.
4. **Never blank a patient.** If data stops, show the last value, greyed, with "NO DATA · 6 s". If the server connection drops, a top banner says "Connection lost, showing data from 14:02:31".
5. **Never colour alone.** Every state has colour, an icon and a word (for colour-blind users, WCAG 2.2 AA).
6. **Looks familiar.** The ward screen is a grid of bed tiles with a coloured title bar, like GE and Philips central stations.
7. **A trust bar on every bed**, like Masimo's Signal IQ: a thin bar under the waveform showing how much we trust this bed's data (from 0 to 1).
8. **One alert per bed per event.** Repeats update the same alert; they never stack new ones.
9. **Privacy:** patient initials and age only. A "hide names" switch is on by default.
10. **Readable from 2 metres:** heart rate and SpO2 numbers at least 40 px on the ward screen.
11. **Dark theme**, because ICUs are dim at night. No pure black (#000).
12. **Every automatic action shows an "Undo"** where it appears, and in the action log.
13. **The bedside nurse is the referee.** Every untrusted or unsure bed asks "checked at the bedside?" with two buttons: Patient OK / Patient NOT OK.
14. **Speed:** a bed tile updates within 1 second of the data. Waveforms are drawn on `<canvas>`, not SVG (12 live waveforms).
15. **Motion:** only alarm flashing and the waveform sweep move. Respect "reduce motion": flashing becomes a steady thick border.

### B1. Colour tokens (product app)
| Token | Hex | Use |
|---|---|---|
| `--bg` | #0A1628 | page (navy) |
| `--surface` | #12284A | tiles, panels |
| `--elevated` | #1A3560 | dialogs, menus |
| `--border` | #24406B | lines |
| `--text` | #F5F8FC | main text |
| `--text-2` | #B8C9E0 | secondary text |
| `--muted` | #7D93B2 | labels, units |
| `--accent` | #4A90E2 | buttons, links, focus ring (blue) |
| `--alarm-high` | #FF4D4F | red, high priority only |
| `--alarm-med` | #FFD166 | yellow, medium only |
| `--alarm-low` | #22D3EE | cyan, low / technical only |
| `--untrusted` | #8A94A6 | grey, used with 45° stripes |

**Fonts:** IBM Plex Sans (text) and IBM Plex Mono (numbers, so digits don't jump).

---

## Part C. Who uses the app (from R7)

| Role | Where they are | What they need | Main screens |
|---|---|---|---|
| **Central-station nurse** | nursing station | see every bed; react to the right bed fast | Ward, Bed, Alerts |
| **Bedside nurse** | at the bed | short phone alerts; confirm "patient OK / not OK" | Telegram, Bed (tablet) |
| **Doctor / tele-ICU** | on call or in a remote centre | which beds need them; which data to distrust | Census, Bed |
| **Biomedical engineer** | biomed workshop | fix loose and drifting sensors and faulty devices | Tickets |
| **IT security** | IT office | attacks, cut-offs, evidence, the CERT-In report | Security, Incident, Report |
| **Demo operator** (us) | — | run the ward script for the video | Demo control |

---

## Part D. The screen map (13 screens)

```
Landing ──► Login (pick a role)
              │
   ┌──────────┼───────────────┬───────────────┬──────────────┐
   ▼          ▼               ▼               ▼              ▼
 WARD (S2)  CENSUS (S5)    TICKETS (S9)   SECURITY (S6)   DEMO (S12)
 nurse      doctor         biomed         IT              operator
   │          │               │               │
   ▼          ▼               │               ▼
 BED (S3) ◄───┘               │           INCIDENT (S7) ──► REPORT (S8)
   │                          │
   ▼                          │
 ALERTS (S4)                  │
                              │
 Shared, from the menu: BRIEFING & WORKLOAD (S10) · ACTION LOG (S11) · Logout
```

**Main screens for the video (6):** S2 Ward · S3 Bed · S6 Security · S7 Incident · S8 Report · plus the Telegram alert.
**Supporting screens (7):** S0 Landing · S1 Login · S4 Alerts · S5 Census · S9 Tickets · S10 Briefing · S11 Log · S12 Demo.

**App frame (every screen after login):**
- **Left rail (72 px):** icons and labels for the screens this role can open.
- **Top bar (56 px):** ward name, clock, live-connection dot ("LIVE" / "RECONNECTING"), role, user menu (Logout).
- **Hidden alert strip:** if any high alarm exists, a red strip under the top bar shows it on **every** screen, so nothing is missed.

---

## Part E. Every screen in detail

### S0 · Landing
- **Who:** anyone (judges, visitors). **Route:** `/`
- **Purpose:** say what SentinelWard is in 5 seconds and get you in.
- **Layout (desktop):**
```
┌────────────────────────────────────────────────────────────┐
│  SentinelWard                                  [ Log in ]   │
│                                                             │
│     Patient, Sensor, or Hacker?                             │
│     Real-time AI on IBM LinuxONE that tells, for every      │
│     hospital bed, whether a scary reading is real.          │
│     [ Open the live ward ]   [ How it works ↓ ]             │
│                                                             │
│  ── live mini-ward: 4 small bed tiles, one goes red ──      │
│                                                             │
│  3 cards: Real emergency · Loose / drifting sensor · Hacker │
│  Footer: Team TessNova · IBM Z Datathon 2026 · GitHub link  │
└────────────────────────────────────────────────────────────┘
```
- **Data:** the mini-ward uses `GET /api/ward/preview` (4 beds, read-only).
- **States:** if the backend is down, the mini-ward shows a still image with "Live demo offline".
- **Actions:** Log in → S1. Open the live ward → S1 with the role pre-set to Nurse.

### S1 · Login (pick a role)
- **Who:** everyone. **Route:** `/login`
- **Purpose:** demo login with one click per role. There's no real hospital login, so we say so.
- **Layout:** a centred card showing 5 role buttons (Central nurse · Doctor / tele-ICU · Biomed · IT security · Demo operator), each with a one-line description. Below: "Demo accounts. A hospital would connect its own sign-in."
- **Data:** `POST /api/session {role}` returns `{token, role, name}`, kept in memory and sessionStorage.
- **States:** a loading spinner on the chosen button; if it fails, an inline error with Retry.
- **Actions:** pick a role, which opens that role's home (Ward, Census, Tickets, Security, Demo). **Logout** (user menu, every screen) clears the session and returns to S1.

### S2 · Ward (central station). Main screen
- **Who:** central-station nurse (home), doctor and IT (read-only). **Route:** `/ward`
- **Purpose:** see all 8–12 beds; know in 2 seconds which bed needs someone and why.
- **Layout (desktop 1920×1080):**
```
┌ top bar: ICU-A · 14:06:12 · ● LIVE · Nurse Priya ▾ ───────────────────────────┐
├ summary row ───────────────────────────────────────────────────────────────────┤
│ Beds 12 │ Alarms now 2 │ Untrusted 1 │ Alarms we stopped today 37 │ Avg trust 0.94│
├ bed grid (4 × 3) ───────────────────────────────────────┬ right rail (360 px) ─┤
│ ┌Bed 1 ─────────┐ ┌Bed 2 ─────────┐ ┌Bed 3 ▓RED▓───┐ ┌.│ ACTIVE ALERTS        │
│ │RK, 64 M       │ │SA, 51 F       │ │MD, 70 M      │ │ │ ● Bed 3 Emergency    │
│ │ECG ~~~~~~~~~~ │ │ECG ~~~~~~~~~~ │ │ECG ~~/\~~~~  │ │ │   VF suspected · 0:42│
│ │PLETH ~~~~~~~~ │ │PLETH ~~~~~~~~ │ │PLETH ~~~~~   │ │ │   [Ack] [Open]       │
│ │HR 82 SpO2 97  │ │HR 76 SpO2 98  │ │HR 0? SpO2 88 │ │ │ ▨ Bed 7 Untrusted    │
│ │BP 118/72      │ │BP 124/80      │ │BP 70/40      │ │ │   check by hand      │
│ │trust ▮▮▮▮▮▮▯  │ │trust ▮▮▮▮▮▮▮  │ │trust ▮▮▮▮▮▯▯ │ │ │ ◆ Bed 4 Loose sensor │
│ │● Normal       │ │● Normal       │ │▲ EMERGENCY   │ │ │   alarm silenced     │
│ └───────────────┘ └───────────────┘ └──────────────┘ │ ├─ recent events ──────┤
│  … beds 5–12 …                                        │ │ 14:05 Bed 7 cut off  │
│                                                       │ │ 14:04 Bed 4 refit req│
└───────────────────────────────────────────────────────┴──────────────────────┘
```
- **Tablet (1024×768):** grid 3 × 4 with waveforms hidden (numbers only); the right rail becomes a bottom drawer.

**Bed tile, field by field:**

| Field | What it shows |
|---|---|
| Title bar | "Bed 3", patient initials, age and sex. **The colour is the alarm priority** (none / cyan / yellow / red), flashing as in A2. |
| ECG waveform | last 6 seconds, sweeping left to right like a monitor |
| Pleth waveform | the pulse wave from the finger sensor, last 6 seconds |
| Numbers | heart rate, SpO2, blood pressure (arterial line if present, else the last cuff reading with its time) |
| Trust bar | 7 segments, 0–1. Below 0.5 it turns grey-striped. |
| Verdict chip | icon plus word: Normal · EMERGENCY · LOOSE SENSOR · DRIFTING · UNTRUSTED · IT ALERT · EMERGENCY + UNTRUSTED · UNSURE |
| Small icons | 🔕 "alarm silenced (sensor)" · 🛡 "IT investigating" (no nurse alarm) · ⏱ "manual check due in 4:00" |

**What each verdict looks like on a tile:**

| Verdict | Title bar | Body | Extra |
|---|---|---|---|
| Normal | no colour | normal | — |
| REAL EMERGENCY | **red, flashing** | numbers in red | goes to the alert rail and Telegram |
| LOOSE SENSOR | **cyan, steady** | the bad signal greyed out | 🔕 "false alarm silenced · refit clip" |
| DRIFTING SENSOR | **yellow, flashing slowly** | BP shows a "vs cuff: +12 mmHg" chip | biomed ticket created |
| TAMPERING / UNTRUSTED | **grey stripes** | last trusted numbers, "UNTRUSTED · last good 14:02 · 3 min ago" | manual-check timer; "Checked at bedside?" buttons |
| DEVICE UNDER ATTACK (body fine) | no colour | normal | 🛡 small icon only (IT handles it, no nurse alarm) |
| BOTH (emergency + attack) | **red + grey stripes** | "GO NOW · do not trust the screen numbers" | the safety rule: the nurse goes AND the device is cut off |
| UNSURE | **yellow** | "Please check Bed X by hand" | never silent |

- **Data:**
  - `GET /api/ward` returns the beds with their latest numbers, verdict, trust and alarm.
  - The live **WebSocket `/ws`** pushes `vitals` (waveform chunks, 1 per bed per second), `verdict` (every 5 s per bed), `alert` and `action`.
- **Refresh:** tiles update on every WebSocket message. If a bed has no message for more than 3 s, it shows "NO DATA · n s".
- **States:**
  - **Loading:** grey skeleton tiles.
  - **Connection lost:** a top banner, and tiles freeze on the last data with a timestamp.
  - **Empty ward:** "No beds admitted" plus "Open demo control" (operator only).
- **Actions:**
  - Click a tile → S3 Bed.
  - Ack on the alert rail → `POST /api/alerts/{id}/ack`.
  - Keyboard: arrows move between tiles, Enter opens.
- **In the video:** the hero shot. Bed 7 flips to grey stripes while Bed 3 goes red.

### S3 · Bed detail
- **Who:** nurse, doctor (read-only actions), IT (read-only). **Route:** `/bed/:id`
- **Purpose:** for one bed: what is happening, **why the AI thinks so**, and what to do.
- **Layout (desktop):**
```
┌ ← Ward   Bed 3 · MD, 70 M · ▲ EMERGENCY (conf 0.93) ───────── [Ack] [Escalate] ┐
├ left 65%: live signals ───────────────────────────┬ right 35%: "Why" panel ──────┤
│ ECG    ~~~~~/\/\~~~~~~~~~~~~~~~~~ (sweep, 10 s)    │ VERDICT: Real emergency      │
│ PLETH  ~~~~~~~~~~~~~~~~~~~~~~~~~~~                 │ Reasons:                     │
│ ABP    ~~~~~~~~~~~~~~~~~~~~~~~~~~~                 │ • Heart, pulse & BP worsen   │
│ HR 0?  SpO2 88  BP 70/40  RR 28                    │   together (body witness ✔)  │
│ trust ▮▮▮▮▮▯▯ 0.71                                 │ • Network normal (✔)         │
├ 30-minute trend (HR, SpO2, BP lines) ─────────────┤ The six checks (0–1):        │
│ ────────────────────────────────╲________          │ M1 Sensor OK      ▮▮▮▮▮▮▯ .88│
│ events: ◆14:01 cuff  ▲14:05 alarm                  │ M2 Real alarm     ▮▮▮▮▮▮▮ .95│
├ two witnesses ────────────────────────────────────┤ M3 Body agrees    ▮▮▮▮▮▮▯ .90│
│ BODY: beat→pulse delay 212 ms (usual 205±15) ✔     │ M4 Not a replay   ▮▮▮▮▮▮▮ .99│
│ NETWORK: 1 msg/s ✔ · sender ✔ · fresh ✔            │ M5 Network OK     ▮▮▮▮▮▮▮ .97│
│                                                    │ M6 No drift       ▮▮▮▮▮▮▯ .91│
├ bedside check (referee) ──────────────────────────┤ Actions taken (with Undo):   │
│ Checked at the bedside?  [Patient OK] [NOT OK]     │ 14:05 Nurse alerted (A1)     │
└────────────────────────────────────────────────────┴──────────────────────────────┘
```
- **Tablet:** a single column (signals → why → actions).
- **Untrusted variant:**
  - The signal area shows the **last trusted 10 seconds**, frozen and labelled "LAST TRUSTED · 14:02:11".
  - Live incoming data shows in a small greyed box, "incoming (not trusted)".
  - A **manual-check panel** shows: "Check pulse and breathing by hand", a counter "next check in 4:59", and a [Record hand check] form (HR, SpO2 by portable device, notes).
- **Data:**
  - `GET /api/beds/:id` returns the latest numbers, verdict, reasons, the six scores and actions.
  - `GET /api/beds/:id/history?minutes=30` returns trends and events.
  - The WebSocket is filtered to this bed.
- **Actions:**

  | Button | Request |
  |---|---|
  | Ack | `POST /api/alerts/{id}/ack` |
  | Escalate | `POST /api/alerts/{id}/escalate` |
  | Patient OK / NOT OK | `POST /api/beds/:id/bedside-check {result, by}` (logged; shown on S2) |
  | Record hand check | `POST /api/beds/:id/manual-reading` |
  | Undo (IT role only) | `POST /api/actions/{id}/undo` |
- **States:** loading skeleton; "bed not found" with Back to Ward; disconnection banner as on S2.

### S4 · Alerts and escalation
- **Who:** nurse, doctor. **Route:** `/alerts`
- **Purpose:** every alert, who has it, how long it has waited, and the escalation ladder.
- **Layout:** filter tabs (Open · Acknowledged · All), then a table:

  | Time | Bed | Priority (colour + word) | What | Sent to | Ladder step | Waiting | Actions |
  |---|---|---|---|---|---|---|---|

  A row opens a side sheet with the ladder: "Nurse Priya (sent 14:05:03, not acked) → 30 s → Nurse Ravi (sent 14:05:33) → 30 s → all nurses + doctor", the response times, and the Telegram message as sent.
- **Data:** `GET /api/alerts?status=open`, plus WebSocket `alert` updates.
- **Rules:**
  - High alerts climb the ladder after **30 s in the demo / 60 s in the real design** without an ack (DESIGN; the Vocera-style ladder from the team brief).
  - Integrity-only alerts never go to nurses.
- **States:** empty → "No open alerts. All beds calm."

### S5 · Census (doctor / tele-ICU)
- **Who:** doctor (home), tele-ICU. **Route:** `/census`
- **Purpose:** a compact list for someone watching from afar, sorted by who needs a doctor. **Trust is a column**, because remote viewers are the ones a hacker fools (R7).
- **Layout:** a table sorted by priority, then trust:

  | Bed | Patient | Verdict | Trust | HR | SpO2 | BP | Last bedside check | Escalated to me |
  |---|---|---|---|---|---|---|---|---|

  A banner appears if any bed is untrusted: "1 bed's data can't be trusted. Don't act on its numbers without a bedside check."
- **Data:** `GET /api/ward`, WebSocket.
- **Actions:** a row → S3 (read-only, plus "Call the bedside nurse", which sends a Telegram ping).

### S6 · Security (IT)
- **Who:** IT security (home). **Route:** `/security`
- **Purpose:** see attacks, cut-offs and every monitor's network health. **Never** shows clinical alarms beyond "a bed is affected".
- **Layout:**
```
┌ summary: Devices 12 │ Isolated 1 │ Open incidents 1 │ Report clock 5:41:12 left ┐
├ device table ─────────────────────────────────────────┬ live attack feed ───────┤
│ Device   Bed  Model     Firmware  Msg rate  Fresh  Net│ 14:04:51 Bed 7 replay   │
│ MON-07   7    SimMon v2  1.4      1.0/s ✔   ✔   0.12▨│   match 0.998 (M4)      │
│ MON-03   3    SimMon v2  1.4      1.0/s ✔   ✔   0.96 │ 14:04:52 cut off (A2)   │
│ …                                                     │   [Undo]                │
├ network witness for selected device ──────────────────┤ 14:05:10 evidence      │
│ message rate (line, 10 min) · sender check · time gaps│   frozen (A3)           │
└───────────────────────────────────────────────────────┴─────────────────────────┘
```
- **Data:**
  - `GET /api/devices` returns, per device: id, bed, model, firmware, message rate, freshness, M5 score, M4 score, status.
  - `GET /api/devices/:id/network?minutes=10`.
  - WebSocket `action` and `alert` (integrity).
- **Actions:**

  | Button | Request |
  |---|---|
  | Cut off device | `POST /api/devices/:id/isolate` (asks "are you sure?"; logged) |
  | Reconnect / Undo | `POST /api/actions/{id}/undo` |
  | Open incident | → S7 |
  | Fleet hunt | `POST /api/fleet-hunt {model}` → lists same-model devices to watch (A4) |
- **States:** "No incidents" calm state, plus the device table.

### S7 · Incident and evidence
- **Who:** IT. **Route:** `/incident/:id`
- **Purpose:** one attack, minute by minute, with the evidence fingerprints, ready for a report.
- **Layout:**
  - **Top:** incident title ("Replay attack on MON-07, Bed 7"), status, start time, 6-hour CERT-In clock.
  - **Left:** a vertical timeline (each event: time, what, who or which agent, link).
  - **Right:** evidence list (readings file, network log, verdict log), each with size and **SHA-256 fingerprint**, plus Download.
  - **Bottom:** affected beds, and actions taken with Undo.
- **Data:** `GET /api/incidents/:id`, `GET /api/incidents/:id/evidence`.
- **Actions:** [Draft CERT-In report] → S8; [Close incident] (asks for a reason).

### S8 · CERT-In report draft
- **Who:** IT. **Route:** `/incident/:id/report`
- **Purpose:** the agent (A5) has drafted the report; a **person** checks it and sends it. We never auto-send.
- **Layout:**
  - **Left:** the editable draft in sections (organisation, contact, time noticed, time occurred, type of incident, affected systems, description, actions taken, evidence list).
  - **Right:** the countdown "Report within 6 hours: 5:41:12 left" and a checklist (facts checked · evidence attached · approver).
  - **Bottom:** [Save draft] [Download PDF] [Mark as sent by me], which records the name and time.
- **Data:** `GET/PATCH /api/reports/:id`, `POST /api/reports/:id/mark-sent`.
- **Rule:** the "Mark as sent" button stays disabled until all checklist items are ticked, with a note saying why.

### S9 · Biomed tickets
- **Who:** biomedical engineer (home). **Route:** `/tickets`
- **Purpose:** sensor and device repair jobs from loose and drifting verdicts (A6).
- **Layout:** a board with 3 columns (New · In progress · Done). Each card shows:
  - the device and bed,
  - the problem ("BP line reads 12 mmHg above cuff for 18 min, drifting"),
  - the suggested fix ("Re-level and re-zero the transducer; take a cuff reading"),
  - a "times this device had issues (30 days)" counter.

  On the side: a "devices with repeat problems" list.
- **Data:** `GET /api/tickets`, `PATCH /api/tickets/:id {status, note}`.

### S10 · Shift briefing and workload
- **Who:** nurses, doctor. **Route:** `/briefing`
- **Purpose:** the handover summary (A8) and nurse alarm load (A7).
- **Layout:**
  - **Tab 1, Briefing:** an AI-written plain summary (by IBM Granite), "since 08:00": incidents, untrusted beds, tickets open, **Blind Time** per bed (minutes with no trusted data).
  - **Tab 2, Workload:** per nurse, alarms received in the last 2 h (bar chart) with a line at 40 (research: 40+ alarms in 2 h raises workload); a warning chip if over.
- **Data:** `GET /api/briefing?since=`, `GET /api/workload?hours=2`.

### S11 · Action log
- **Who:** all (read); IT (undo). **Route:** `/log`
- **Purpose:** every automatic action, who or what did it, and its undo. This is safety rule 3.
- **Layout:** a filterable table (Time · Agent or person · Action · Bed / device · Approved by · Undo) plus a search box.
- **Data:** `GET /api/actions?limit=200`.

### S12 · Demo control
- **Who:** demo operator only. **Route:** `/demo`
- **Purpose:** run the ward script for the video, and reset.
- **Layout:**
  - A scenario list: Full ward script (12 min) · Real emergency only · Loose sensor · Drift · Replay attack · Fake flatline · Flood.
  - Controls: [Run] [Pause] [Reset ward], plus a speed control (1× / 2× / 5×).
  - A live timeline of what will happen when.
- **Data:** `POST /api/demo/run {scenario, speed}`, `POST /api/demo/reset`.
- **Rule:** hidden from every other role.

---

## Part F. Telegram messages (exact templates)

**Each message has:**
- a bold first line (bed and what), the reason, the action, and a time;
- for high alerts, a **12-second waveform image** (`sendPhoto`, caption ≤ 1024 characters);
- buttons (`callback_data` ≤ 64 bytes, e.g. `ack:a_3f9c` or `ok:b7:a_3f9c`).

| Event | To | Message | Buttons |
|---|---|---|---|
| Real emergency | assigned nurse, then ladder | 🔴 **Bed 3 — possible heart emergency. Go now.**<br>HR 0?, SpO2 88, BP 70/40. Body and network both look real.<br>14:05:03 | [On my way] [Escalate] |
| Escalation (30 s demo / 60 s real, no ack) | next nurse + doctor | 🔴 **Bed 3 — emergency, not acknowledged for 30 s.** Please go. | [On my way] |
| Loose sensor | bedside nurse | 🔵 **Bed 4 — finger sensor loose.** False alarm silenced. Please refit the clip. | [Done] |
| Drifting sensor | bedside nurse + biomed | 🟡 **Bed 5 — blood pressure may be drifting** (12 mmHg off the cuff). Re-level and re-zero the line; take a cuff reading. | [Done] [Need biomed] |
| Untrusted (tampering) | bedside nurse | ⚪ **Bed 7 — monitor can't be trusted.** Check pulse and breathing by hand. Use a portable monitor. | [Patient OK] [Patient NOT OK] |
| Both | bedside nurse + ladder | 🔴 **Bed 7 — GO NOW. Do not trust the screen numbers.** Possible emergency on a monitor that may be tampered with. | [On my way] [Escalate] |
| Device under attack | IT group only | 🛡 **MON-07 (Bed 7): replay attack suspected.** Device cut off 14:04:52. Evidence saved. Report clock: 6 h. | [Open incident] [Undo cut-off] |
| Unsure | bedside nurse | 🟡 **Bed 9 — readings unclear.** Please check by hand. | [Patient OK] [Patient NOT OK] |

**After a button press:** edit the same message to show "✅ Acknowledged by Priya at 14:05:21", so the chat never fills up with duplicates.
**Rate rule:** at most 1 message per second per chat. Queue the rest, and merge repeats for the same bed.

---

## Part G. Backend contract (LOCKED in doc 00 v1; summary)

| Method | Path | Returns / does |
|---|---|---|
| POST | /api/session | demo login by role |
| GET | /api/ward | all beds: latest numbers, verdict, trust, alarm |
| GET | /api/ward/preview | 4 beds for the landing page |
| GET | /api/beds/:id | one bed in full: reasons, six scores, actions |
| GET | /api/beds/:id/history?minutes= | trends and events |
| POST | /api/beds/:id/bedside-check | referee result |
| POST | /api/beds/:id/manual-reading | hand-check numbers |
| GET | /api/alerts?status= | alerts with ladder state |
| POST | /api/alerts/:id/ack · /escalate | — |
| GET | /api/devices · /api/devices/:id/network | IT device table and network witness |
| POST | /api/devices/:id/isolate | cut off (logged, undoable) |
| POST | /api/fleet-hunt | same-model devices |
| GET | /api/incidents/:id · /evidence | incident and evidence |
| GET/PATCH | /api/reports/:id | CERT-In draft |
| POST | /api/reports/:id/mark-sent | a human records sending |
| GET/PATCH | /api/tickets · /api/tickets/:id | biomed board |
| GET | /api/briefing · /api/workload | A8 and A7 |
| GET | /api/actions | action log |
| POST | /api/actions/:id/undo | undo |
| POST | /api/demo/run · /api/demo/reset | demo control |
| WS | /ws | live: `vitals`, `verdict`, `alert`, `action` messages (formats = doc 00 v1) |

---

## Part H. Done checklist for Antara
- [ ] All 13 screens reachable; each role sees only its screens
- [ ] Ward screen shows 12 live beds, each tile updating within 1 s
- [ ] Every verdict's look matches the table in S2
- [ ] No patient is ever blank (test: stop the data for a bed → "NO DATA · n s")
- [ ] Alarm colours used for alarms only; every state also has an icon and a word
- [ ] Bedside "Patient OK / NOT OK" works from the app and from Telegram
- [ ] Every automatic action shows an Undo, and the log matches
- [ ] Tablet layout works (1024×768)
- [ ] Reduce-motion respected; contrast passes WCAG AA
- [ ] Telegram: emergency with waveform image, ack edits the message, escalation after 30 s (demo)
