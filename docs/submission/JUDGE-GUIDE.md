# Judge guide

[Explore everything yourself: screens, setup, logs and code](../../README.md#explore-everything-yourself).

[Results manifest: exact evidence files, run cohorts and limits](../evidence/RESULTS-MANIFEST.md).

## Criterion 1 — value and theme

- SentinelWard checks replayed patient, sensor and attack cases. Active monitor alarms retain emergency precedence; available last trusted values are retained when data becomes untrusted. B07’s 88 legacy counts per run are a counter artefact before first data; 0 empty samples after first data in all four runs (N/F1/F2/F3). Rendered-screen continuity was not measured (`docs/evidence/WARD-RUN.md`). Design: `docs/ARCHITECTURE.md`; screens: **Ward** and **Bed** (`web/src/pages/Ward.tsx`, `web/src/pages/Bed.tsx`).
- The lab ward replays open ICU recordings from PhysioNet/CinC, VTaC, MIMIC-III and VitalDB. Proof: `docs/OPEN-SOURCE.md`; bed-by-bed demo sources: `docs/spec/12-ward-script.md`.
- Twelve monitors publish once per bed per second into six checks and a decision layer (`docs/spec/00-contract-v1.2.md`). The checked-in LinuxONE run shows live telemetry and verdicts (`deploy/evidence/demo-watch.md`).
- Alarm fatigue, advice only (the monitor alarm still sounds; nothing is suppressed): at the live thresholds M2 marks **85.1%** of false CinC held-out alarms "likely false" (97/114) and misses **2.7%** of true ones (2/74); VTaC test **84.1%** (290/345) and **4.4%** (6/137). Recompute: `python ml_v2/results/fatigue.py` → `docs/evidence/raw/fatigue.txt`; table in `docs/evidence/ML-RESULTS.md`.
- A real VT alarm reached `EMERGENCY` in **3.019 s** and the ward API in **3.139 s** (`deploy/evidence/smoke-h6-checkpoint1.md`).

## Criterion 2 — originality and implementation

- The live brain implements M1–M6, bounded windows, model fallback and the eight-verdict safety precedence. Proof: `brain/README.md`.
- The two-lead M2 model, training pipeline and portable hash-checked inference were written on build day. Proof: `ml_v2/README.md`; model artifact and metrics: `ml_v2/results/heldout2.json`.
- A1–A8 cover alert escalation, cut-off and Undo, SHA-256 evidence, fleet hunt, CERT-In draft, biomed tickets, workload and IBM Granite briefing. Proof: `agents_v2/REPORT.md`; screens: **Security**, **Incidents**, **CERT-In report draft**, **Repair tickets**, **Briefing and workload**.
- Open-source software, model tooling and datasets are linked and attributed in `docs/OPEN-SOURCE.md`.
- What we built differently from our 12 Oct abstract, and why (trained fusion → fixed safety precedence, LangGraph → own allow-list engine, Snap ML/XGBoost → scikit-learn trees trained on s390x, 9 datasets → 4): [README, "What changed from our abstract, and why"](../../README.md#what-changed-from-our-abstract-and-why).

## Criterion 3 — IBM LinuxONE design and evidence

- Platform evidence shows `s390x`, machine type **9175**, IBM z/VM and the `nnpa` CPU feature (`deploy/evidence/lscpu.txt`, `deploy/evidence/proc-sysinfo.txt`, `deploy/evidence/nnpa-cpuinfo.txt`).
- M2 training results record host `tessnovabuild`, machine `s390x`, held-out CinC score **0.862** and VTaC VT score **0.832** for the two-lead model (`ml_v2/results/heldout2.json`). The 1D-CNN runs live on `nnpa:0` on a second LinuxONE guest as a shown-only second opinion that never changes a decision (`docs/evidence/ML-RESULTS.md`, `ml_v2/results/cnn_result.json`).
- Separate from the secured agents-on systemd ward, the six-container design applies non-root users, read-only filesystems, dropped capabilities and resource limits to four app containers (`deploy/containers/README.md`, `deploy/containers/compose.yaml`). Saved captures show all six services up, api/hub/db healthy, four-app hardening and two full ward replays before service authentication: `docs/evidence/CONTAINERS.md`, `docs/evidence/raw/resources-now.txt`.
- The secured systemd hub design uses TLS 1.3, deny-by-default dynsec ACLs, per-device accounts, agents and the witness (`security_v2/SECURITY.md`). Live security test on LinuxONE: **15/15 PASS** (`docs/evidence/SECURITY.md`, raw `docs/evidence/raw/security-live-20261017T140649Z.json`).
- Container hub: **137/137 auth checks, anonymous refused** (`docs/evidence/raw/containers-auth/auth.txt`); authenticated static service accounts + topic ACLs, plaintext internal MQTT, four hardened app containers, no agents/witness. Authenticated replay is only a **40-second spot check** (`docs/evidence/CONTAINERS.md`); historical full replays predate auth.
- Existing process snapshots cover live ward load (`deploy/evidence/ps-top-11beds-T0430.txt`, `deploy/evidence/ps-top-10beds-T1000.txt`). The bundled short-run originals (`docs/evidence/raw/scale/`) reproduce **96 beds**, median/max tick 640.44/1121.65 ms and 0 recorded drops/invalid on one CPU; runs last about 3 minutes. The older bundled scale capture rejected all 5,220 extra-bed messages. Memory plateau evidence is for 12 beds, with no 96-bed soak (`docs/evidence/SCALE.md`, `docs/evidence/RESOURCES.md`).

## Criterion 4 — clarity and live demonstration

- The planned **2:50** alternate sequence, words and captions are in `docs/submission/VIDEO-SHOTLIST.md`; the primary narration is `docs/VIDEO-SCRIPT.md`; it includes the live LinuxONE terminal, ward, phone alert, cut-off and Undo, CERT-In draft, containers and model results.
- The repeatable event order comes from `docs/spec/12-ward-script.md`; the screen routes are defined in `web/src/App.tsx`.
- The video states the honest limit: a laboratory prototype replaying recordings, not a clinical device (`docs/README-final-draft.md`).
- Latest night run N (build `4348467`): **12/12** bed checks, B12 UNSURE **17:04**, 11 nurse alerts (`docs/evidence/raw/wardrun-night/judgeN.txt`, `metricsN.txt`). This is one post-fix run; witness counts are distinct broker client IDs per bed topic/window, not cryptographic identity of each frame (`security_v2/sw_sec/features.py`, `brain/sw_brain/detectors.py`).
- Historical ward runs F1–F3 (build `f7fef1c`, agents on): beds 12/12, 11/12, 11/12 (B12's weak second sender seen in 1 of 3 runs); median time-to-safe B06 3.1 s, B07 19.2 s, B05 23.2 s, B10 23.2 s (scripted attack start → bed untrusted, nurse told and device cut off); 11 nurse alerts per run; Telegram 22 sent, 25–26 edited, 0 failed per run; B03 alert acknowledged at ladder step 2 after 44.6 / 47.4 / 46.5 s; IBM Granite briefing in all three (`docs/evidence/WARD-RUN.md`).
- Video (2:40): https://youtu.be/JEtgz6hSekM — recorded from one live full-ward run (18 Oct, zero start, 1× speed) plus live read-only LinuxONE commands; ends on the exact title `[TessNova_IBM Z Datathon 2026 Project]`. Narration is synthetic (Kokoro TTS) and the opening alarm beep and music are added sound effects.
