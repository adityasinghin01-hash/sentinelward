# Aditya (automation and AI agents): work plan v3 (7 Oct, updated 10 Oct: see "Added 10 Oct")

## Your data and your AI
- **Data:**
  - **VitalDB**: real surgeries where the arterial line and the arm cuff measure the same patient. You use it to catch slowly drifting blood-pressure sensors.
  - **Our own logs**: response times tune the escalation timers; fault history predicts failing sensors; alarm counts balance nurse workload.
- **AI:**
  - **M6**, the drift watcher;
  - **IBM Granite**, which writes plain-language messages (it never decides);
  - the **agent engine** that carries out the AI's decisions.

## Your job in one paragraph
You make the AI's decisions happen. You build the agent engine that runs every agent safely (fixed allow-list, human approval where needed, every action logged with an undo). On top of it you build the alert ladder (with Antara), the CERT-In report draft, biomed tickets, the workload warning, the shift briefing, the Granite writer and the drift watcher M6. **Agents are the helpers; the AI decides.**

## What you own (full detail: R11, Drive doc 09)
- **Agent engine:**
  - LangGraph (with `interrupt()` for human approval and a Postgres checkpointer) or IBM BeeAI;
  - routes each verdict to the right agent;
  - only allow-listed actions;
  - every action goes on `ward/action` with an undo id (doc 00 v1, section 4).
- **A1 alert and escalation** (with Antara):

  | Step | Who gets it | When |
  |---|---|---|
  | 1 | the assigned nurse | at once |
  | 2 | the next nurse | after **30 s (demo)** / 60 s (real) with no ack |
  | 3 | all nurses + the doctor | after another 30 s / 60 s |

  - Telegram message with buttons; an ack edits the message.
  - **A BOTH verdict always alerts the nurse.**
  - **Why the phone is only the second channel (checked 7 Oct):** the health ministry's DGHS told central government hospitals in April 2024 to restrict phone use on duty in ICUs, HDUs, post-op wards and theatres (infection risk). Kauvery Hospitals (Sep 2026) moved 12,000+ staff off consumer chat apps onto a hospital messaging app (NetSfere). So: Telegram in the demo, the hospital's own app in real life; the central screen works without phones.
- **A5 CERT-In draft:**
  - all form fields (sector = Health, times, affected system, symptoms, actions);
  - a 6-hour clock;
  - **never sends**; a person does.
  - Say "DPDP breach notice applies **from 13 May 2027**" (not now).
- **A6 biomed tickets:** repeated loose sensor or any drift → a ticket for biomedical engineering (not IT).
- **A7 workload:** more than 40 alarms to one nurse in 2 h → warn the charge nurse. Source: Rasooly et al., Hospital Pediatrics 2021 (26 children's-hospital nurses): more than 40 alarms in the previous 2 hours raised their workload score by 5.5 points.
- **A8 shift briefing:** Granite writes it; every number is checked against the data.
- **A9:** design only.
- **Granite writer:** llama.cpp on LinuxONE (big-endian GGUF model); fixed templates as fallback.
- **M6 drift watcher:**
  - line vs cuff gap of ≥ 10 mmHg at each cuff reading;
  - a Page-Hinkley test on the residual;
  - a shape check;
  - **if the cuff confirms a real drop, it's an EMERGENCY, never "drift".**
  - Must tell Kartik's slow fake drift apart from a real sensor drift (use the network witness and heart–pulse timing).
- **Prompt-injection test** (with Kartik).

## Tool choice (in simple words)
- **Python agents on LinuxONE** (LangGraph or IBM BeeAI): our pick. Patient data never leaves IBM's machine, and it counts for IBM Z points.
- **n8n:** optional, on a laptop, only for one nice visual flow in the video (e.g. the shift briefing). It can't run on LinuxONE.
- **Zapier / Make:** no. They're cloud tools, so patient data would leave, and their free tiers are small (Zapier 100 tasks/month; Make 1,000 credits/month).

## Before 17 Oct
| Date | Do |
|---|---|
| 7 Oct | Toy examples: a LangGraph "hello" graph with an approval pause; a small Granite model with llama.cpp on your laptop; a Telegram bot sending "hello" with buttons (with Antara). |
| 8–10 Oct | VitalDB: find cases with both `SNUADC/ART` (or `Solar8000/ART_*`) and `Solar8000/NIBP_*`; note how often the cuff reads. One page of notes. |
| 11–12 Oct | On paper: the allow-list per agent, the CERT-In template, M6 rules, message templates (Antara has drafts in R8). |
| 13 Oct | ~~Team paper run~~ (dropped 10 Oct). |
| 14–15 Oct | Read llama.cpp's s390x notes. Questions for the session. |
| 16 Oct | Readiness session. |

## During the 24 hours
| Hours | Do |
|---|---|
| 1–6 | Engine skeleton + allow-list; A1 first alert with Antara → **Hour 6: an alert reaches a phone** |
| 6–12 | M6 on VitalDB beds; Granite (or templates); A6 tickets → **Hour 12** |
| 12–16 | A5 CERT-In draft; A8 briefing; A7 workload; injection test |
| 16–19 | Drift tests: how fast drifts are caught; real BP drops never called drift |

## Done checklist
- [ ] Only allow-listed actions; approvals where needed; every action logged with undo
- [ ] Ladder works (30 s demo); BOTH always alerts · [ ] CERT-In draft complete, never auto-sent
- [ ] M6 scores per bed; passes the "real drop" test · [ ] injection test passed

## Added 10 Oct (IBM resources)
- **Granite already runs on LinuxONE in IBM's Jupyter image** (through llama.cpp). IBM's lab `Loan_Approval_Demo.ipynb` scores data with an ML model, looks up rules (RAG) and has Granite write a recommendation. That's the same pattern as our Granite writer for alerts, the CERT-In draft and the shift briefing, so start from it instead of setting up Granite from zero.
- Keep the fixed message templates as the fallback if Granite is too slow on our server.
- The "Predictive AI + Generative AI" mandatory lab is most likely this notebook; do it before 17 Oct (doc 01).
- **M6 (from doc 11):** compare each patient's line-vs-cuff gap with that patient's own normal gap, not a fixed 10 mmHg. VitalDB: 2,759 cases have both the line and the cuff; filter on the anaesthesia record's arterial-line field (aline1).

## Read
Doc 00 v1 · R11 (09) · R9 section 4 (07) · R10: M6 (08) · R12b fact check (10) · Research phases 5.4, 5.5, 5.6, 5.9
