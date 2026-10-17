# Antara Gupta (screens and alerts): work plan v3 (7 Oct, updated 10 Oct: see "Added 10 Oct")

## Your data and your AI
Your screens are where people **see the AI's decisions and the data behind them**:
- every bed's live signals;
- the verdict and its top 3 reasons;
- the six model scores;
- a **trust bar**;
- "alarms we stopped" (proof the AI cuts false alarms).

## Your job in one paragraph
You build everything people see: a web app (judges need a link, so no phone app yet) with **13 screens** for 5 roles. The central-station nurse sees every bed; the bedside nurse gets short phone alerts and confirms "Patient OK / NOT OK"; the doctor sees who needs them and which data not to trust; biomed sees repair tickets; IT sees attacks, evidence and the CERT-In draft. **A hacked bed is never blank.** The pitch and video score (10 of the 40 points) depends on you.

## Your full spec: R8, Drive doc 06 (read it all)
It has, for every screen: who uses it, layout sketch (desktop + tablet), every element, which backend address it reads, how often it updates, loading / empty / error / untrusted states, every button and where it goes, plus every Telegram message.

**The 13 screens:**

| # | Screen | # | Screen |
|---|---|---|---|
| S0 | Landing | S7 | Incident and evidence (main) |
| S1 | Login (pick a role) | S8 | CERT-In report draft (main) |
| S2 | **Ward / central station** (main) | S9 | Biomed tickets |
| S3 | **Bed detail** (main) | S10 | Shift briefing and workload |
| S4 | Alerts and escalation | S11 | Action log |
| S5 | Census (doctor / tele-ICU) | S12 | Demo control |
| S6 | **Security / IT** (main) | | |

## The design rules (simple version)
- **Colours:**
  - Red / yellow / cyan are for alarms only (the international alarm standard).
  - Everything else is calm navy and blue.
  - Untrusted = **grey diagonal stripes** + the words "UNTRUSTED · last good 14:02 · 3 min ago".
- **Never colour alone:** every state has colour + icon + word.
- **Familiar:** the ward screen looks like the central monitoring screens nurses already use (GE, Philips): bed tiles with a coloured title bar.
- **One alert per bed per event**; every automatic action shows **Undo**.
- **The screen comes first, the phone second.** Central government hospitals were told in 2024 to restrict phones on duty in ICUs (DGHS advisory), and big private chains are moving staff to their own messaging apps (Kauvery, Sep 2026). So every alert must be fully usable on the central screen; Telegram is the demo stand-in for the hospital's app.
- **Readable from 2 m:** big HR and SpO2 numbers. Dark theme.

## What to use (detail: R9 section 1, Drive doc 07)
- React + Vite + TypeScript, React Router, Zustand.
- The browser's WebSocket for live data.
- `<canvas>` for monitor-style waveforms; uPlot for 30-minute trends.
- Lucide icons; IBM Plex fonts.
- Build on a laptop → the files are served from LinuxONE.

## What you receive
Exactly the messages and addresses in **doc 00 v1**: `GET /api/ward`, `/api/beds/<id>` … and the live `WS /ws`.

## Before 17 Oct
| Date | Do |
|---|---|
| 7 Oct | Toy examples: a small React page with tiles updating over a WebSocket (dummy data, not our project); a Telegram "hello" bot with buttons (with Aditya). |
| 8–10 Oct | Study the inspiration list in R9 (GE, Philips, Mindray central stations; Masimo Signal IQ; Claroty). Sketch S2, S3, S6 on paper or Figma (designs are allowed). |
| 11–12 Oct | Check every screen against doc 00 v1. README outline. |
| 13 Oct | ~~Team paper run~~ (dropped 10 Oct). |
| 14–15 Oct | Video storyboard with Aditya Singh (which screen in which second). |
| 16 Oct | Readiness session. |

## During the 24 hours (order from R9)
| Hours | Do |
|---|---|
| 1–6 | Shell, login, one live bed tile; Telegram alert with Aditya → **Hour 6** |
| 6–12 | 12 tiles + every verdict look; Bed detail with untrusted mode; Alerts; Security; Incident; Report → **Hour 12** |
| 12–16 | Census, Tickets, Briefing, Log, Demo control; tablet layout → **Hour 16 freeze** |
| 16–19 | Polish for the video |
| 19–22 | README + screen recordings |

## Done checklist
- [ ] All 13 screens; each role sees only its own · [ ] every verdict looks as in R8 · [ ] never a blank patient
- [ ] Bedside "Patient OK / NOT OK" works from screen and Telegram · [ ] ladder visible · [ ] Undo everywhere
- [ ] Tablet layout; contrast and reduce-motion · [ ] README lets a stranger run it

## Added 10 Oct (Participant Guidebook)
- **Judges want screenshots as evidence** of LinuxONE use (containers, security, scalability, compute). Collect them during the build for the video and README.
- **The project title must be:** `[TessNova_IBM Z Datathon 2026 Project]`.
- **The README must link every open-source library** we use.
- **Required:** a video of at most 3 minutes and the GitHub link. **Optional:** a flowchart of the design and a prototype link.
- **The 20-minute ward script (doc 12)** is what the video and your screen recordings follow; doc 15 has the scene list.

- **Whole team:** two IBM AI/ML labs must be completed before we start building (README v4). The readiness session is 16 Oct; join at 7:15 PM IST.

## Read
R8 (06) in full · Doc 00 v1 · R9 section 1 (07) · R7 (05) for why · R12b fact check (10)
