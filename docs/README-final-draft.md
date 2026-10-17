# SentinelWard

Archived draft, not the submission README. Current results and deployment limits: `../README.md` and `evidence/RESULTS-MANIFEST.md`; placeholders below are not measured results.

**[TessNova_IBM Z Datathon 2026 Project]** · Theme 1: real-time AI decisions · Team TessNova

> An ICU alarm goes off. Is it the **patient**, a **loose sensor**, or a **hacker** faking the monitor?
> SentinelWard checks a 12-bed replay every five seconds on IBM LinuxONE, retaining available last trusted values when a monitor becomes untrusted.

[Video (3 min)](VIDEO_LINK) · [Architecture](docs/ARCHITECTURE.md) · [Open source used](docs/OPEN-SOURCE.md)

## The problem
- Most ICU heart alarms are false (88.8% in one large study: Drew et al., 2014), so real ones get lost in the noise.
- Bedside monitors send vital signs over the hospital network. Faking that traffic has been shown in labs; no real hospital case is known yet. We built the defence before the first attack.
- Today a central-station nurse cannot tell a real emergency from a loose lead or forged data in time.

## What SentinelWard does
Twelve monitors stream real recorded ICU signals (one reading per bed per second) into a message hub on LinuxONE. Every 5 seconds, six AI checks score every bed, a decision layer gives one of eight verdicts with reasons, agents act on it, and the central screens and phones show it.

| Check | Question it answers |
|---|---|
| M1 | Is the sensor unusable (flat, clipped, noisy, missing)? |
| M2 | Is this monitor alarm real? (gradient-boosted trees trained on LinuxONE on PhysioNet 2015 + VTaC) |
| M3 | Do heart and pulse still agree for this patient (rate + pulse-arrival time vs the patient's own baseline)? |
| M4 | Is this a replay of earlier data? |
| M5 | Does the network traffic look like an attack (second sender, flood, sequence repeats)? |
| M6 | Is the arterial line drifting away from this patient's own cuff readings? |

Verdicts: NORMAL · EMERGENCY · BOTH (emergency during an attack) · TAMPERING · UNSURE · DRIFTING · LOOSE_SENSOR · DEVICE_ATTACK.

**Safety behavior:** available last trusted values are retained, marked untrusted (B07 screen continuity remains unverified; `evidence/WARD-RUN.md`) · active monitor alarms retain emergency precedence · actions are logged and supported reversible actions have Undo · nothing automatic touches treatment · official reports are drafted by an agent and sent by a person.

## Why IBM LinuxONE
- The whole ward's decision-making runs on one IBM z17 (s390x) server: hub, six checks, decision layer, agents, database, evidence store. The shown-only chip second opinion reads vitals over TLS on a second LinuxONE guest (`evidence/ML-RESULTS.md`).
- Systemd is the secured agents-on ward. The separate six-container stack has process hardening but omits agents/witness and permits anonymous MQTT internally (`EXPLORE.md`).
- Hub locked down with per-device accounts: each monitor may publish only its own bed; TLS for anything off the box.
- The M2 model is trained and served on LinuxONE; IBM Granite writes the shift briefing on LinuxONE. A shown-only CNN second opinion runs on the z17 NNPA (`evidence/ML-RESULTS.md`).
- Load: [x]% CPU and [y] GB RAM for the whole 12-bed ward (measured, see Results).

## Results (measured during the datathon)
[Filled in Phase 4 from `tests_system/results/` and `ml_v2/` reports: M2 held-out scores per alarm type, attacks caught and how fast, missed emergencies, time-to-safe, Blind Time, likely-false advice rates, resource use, security test table.]

## Data (all open)
PhysioNet/CinC 2015 false-alarm challenge · VTaC VT alarms · MIMIC-III Waveform Matched Subset (sample) · VitalDB. The ward replays real recordings; it is a lab ward, not a hospital deployment.

## Run it
- On LinuxONE (systemd): `deploy/deploy.sh` (see `deploy/README.md`).
- As containers: `deploy/containers/README.md`.
- Screens: open the backend URL; one-click role login (nurse, doctor, IT, biomedical, operator). PIN-based authentication and optional demo login are described in the current README.

## Repository map
`common/` shared message contract · `data/` bed packs from real recordings · `simulator/` ward simulator · `brain/` six checks + decision layer · `ml_v2/` M2 training · `agents_v2/` agents A1-A8 · `security_v2/` hub lockdown, containment, network witness · `backend/` API + live feed + PostgreSQL · `web/` screens · `attacks/` red-team test sender · `tests_system/` system tests and results · `deploy/` server, containers, Granite · `docs/` architecture, specs, video script.

## Honest limits
Lab ward with replayed recordings, not a clinical device. Scores are not calibrated clinical probabilities. M5's network rules were tested on our own attack runner, not on a real hospital network. Not approved for clinical use (in India this would follow the CDSCO medical-device software route).

## Team TessNova
Aditya Singh (lead) · Aditya Singhal · Aditya · Kartik · Antara Gupta
