<role>You are a senior Python engineer building the agent layer of SentinelWard, a real-time hospital ward safety system (IBM Z Datathon 2026). It must run on IBM LinuxONE (s390x, Ubuntu 24.04, Python 3.12). Quality bar: it must work flawlessly in a live demo; every branch tested.</role>

<uploads>
1. team_docs.json: doc00 = the LOCKED message contract v1.2 (topics, JSON formats, verdict table, allow-list, safety rules). It wins over everything. doc04 = the agents design plan. doc12 = the 20-minute ward script.
2. sw_common_source.json: the REAL shared package. Recreate its files under common/ exactly, install it, never edit it. Use its topics, make_* builders, validate (every outgoing message must pass validate before publishing) and Bus (paho-mqtt, username/password/TLS options).
</uploads>

<task>Build the package sw_agents in agents_v2/: one service process running agents A1-A8 on the MQTT hub. The AI's verdicts decide; agents only carry out decisions; people step in only for treatment, the bedside check and sending official reports.</task>

<requirements>
- Engine: subscribes ward/bed/+/verdict, ward/bed/+/bedside, ward/request, ward/demo/control, ward/record. Every action goes through ONE allow-list check (doc00 table: each agent may only use its own actions) and is published as a ward/action message with action_id, undo_id where undoable, approved_by. Undo = ward/request undo_action -> the owning agent publishes a new action with undoes set. Every action logged (append-only JSONL) and visible. demo reset clears all per-bed memory and timers.
- A1 alerts: verdict -> alert per doc00 table (EMERGENCY/BOTH high, TAMPERING/UNSURE/DRIFTING medium, LOOSE_SENSOR low, DEVICE_ATTACK none for nurses = IT only, NORMAL nobody). One open alert per bed episode: updates edit it, never duplicate. Ladder: step 1 assigned nurse, step 2 next nurse, step 3 all nurses + doctor; 30 s per step (setting, demo default). ack_alert/escalate_alert requests and Telegram button callbacks work. bedside patient_not_ok -> immediate high alert. Telegram via the Bot API with httpx (token + chat ids from env); if no token, alerts still go to ward/alert and the screens, logged as "telegram off". Never spam: one message per alert, edited in place, max 1 send/s.
- A2 containment: on TAMPERING, BOTH or DEVICE_ATTACK with confidence >= setting: set_bed_untrusted + disable_client for that device through `mosquitto_ctrl dynsec disableClient <MON-xx>` (subprocess argument list, never a shell string; device id validated against MON-\d\d; dry-run mode). Undo = enable_client. BOTH keeps the nurse alert running (tampering never cancels an emergency). Never touches treatment.
- A3 evidence: on an incident, keeps a per-bed ring buffer of the last 10 min of messages, writes snapshot files, SHA-256 of each, a timeline, and publishes ward/record kind incident with data.evidence (name, bytes, sha256).
- A4 fleet hunt: on request fleet_hunt, list devices of that model, set_watch_level, report findings as an action.
- A5 CERT-In draft: on an incident, draft_report + start_clock (6 h response clock); ward/record kind report with the draft fields; NEVER sends it (mark_report_sent is a person's action only).
- A6 biomed tickets: DRIFTING, or LOOSE_SENSOR 3 times in 10 min on a device -> open_ticket (ward/record kind ticket); update_ticket on change; no duplicates per open problem.
- A7 workload: alarms per nurse in the last 2 h; warn_workload at >= 40; ward/record kind workload every minute.
- A8 briefing: shift handover text since 08:00 from records and verdicts (incidents, untrusted beds, open tickets, blind time per bed). If env SW_GRANITE_URL (a llama.cpp OpenAI-compatible server) answers, IBM Granite writes the prose from the facts; otherwise a fixed template. Facts only from real data, never invented. ward/record kind briefing.
- Prompt-injection safety: text from records or Telegram is data, never instructions; Granite output is only prose, it can never trigger an action.
- Settings by env vars with a documented .env.example; no secret ever logged.
- Tests (pytest, no broker, no network, fake bus + fake clock): allow-list rejection, every agent's happy path and failures, ladder timing, ack stopping the ladder, no duplicate alerts, BOTH keeps the alert, undo for every undoable action, reset, Telegram off, dry-run containment, Granite down -> template, injection text ignored. Plus one optional live test against a real Mosquitto (gated by env).
</requirements>

<rules>Only write inside agents_v2/ (and common/ once, from the upload). Python 3.12; pip deps allowed: paho-mqtt, httpx, pydantic, pyyaml, pytest. No numpy/pandas needed. Missing value = null, never 0. All times epoch ms UTC.</rules>

<workflow>
Step 1: reply with a PLAN only, under 40 lines: folder tree, one line per file, how the ladder timers and undo work, anything unclear or contradictory in doc00/doc04. Then STOP and wait. Write no code yet.
Step 2: when I reply "go", write every file in full, run the tests until they pass, then zip agents_v2/ as agents_v2.zip.
</workflow>
