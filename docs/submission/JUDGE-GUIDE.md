# Judge guide

[Explore everything yourself: screens, setup, logs and code](../../README.md#explore-everything-yourself).

## Criterion 1 — value and theme

- SentinelWard separates a patient emergency, a faulty sensor and forged monitor data, while enforcing “never blank” and “tampering never cancels an emergency.” Proof: `docs/ARCHITECTURE.md`; live screens: **Ward** and **Bed** (`web/src/pages/Ward.tsx`, `web/src/pages/Bed.tsx`).
- The lab ward replays open ICU recordings from PhysioNet/CinC, VTaC, MIMIC-III and VitalDB. Proof: `docs/OPEN-SOURCE.md`; bed-by-bed demo sources: `docs/spec/12-ward-script.md`.
- Twelve monitors publish once per bed per second into six checks and a decision layer (`docs/spec/00-contract-v1.2.md`). The checked-in LinuxONE run shows live telemetry and verdicts (`deploy/evidence/demo-watch.md`).
- Alarm fatigue, advice only (the monitor alarm still sounds; nothing is suppressed): at the live thresholds M2 marks **85.1%** of false CinC held-out alarms "likely false" (97/114) and misses **2.7%** of true ones (2/74); VTaC **84.1%** (290/345) and **4.4%** (6/137). Recompute: `python ml_v2/results/fatigue.py` → `docs/evidence/raw/fatigue.txt`; table in `docs/evidence/ML-RESULTS.md`.
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
- The hardened six-container design uses non-root users, read-only filesystems, dropped capabilities and resource limits (`deploy/containers/README.md`, `deploy/containers/compose.yaml`). Live: all six containers up, api/hub/db healthy, hardening and two full in-container ward runs: `docs/evidence/CONTAINERS.md`, `docs/evidence/raw/resources-now.txt`.
- The secured hub design uses TLS, deny-by-default ACLs and per-device identities (`security_v2/SECURITY.md`). Live security test on LinuxONE: **15/15 PASS** (`docs/evidence/SECURITY.md`, raw `docs/evidence/raw/security-live-20261017T140649Z.json`).
- Existing process snapshots cover live ward load (`deploy/evidence/ps-top-11beds-T0430.txt`, `deploy/evidence/ps-top-10beds-T1000.txt`). Scale: one brain container keeps up with **96 beds** using 22% of its 5 s tick on 1 CPU, memory flat (`docs/evidence/SCALE.md`, `docs/evidence/RESOURCES.md`).

## Criterion 4 — clarity and live demonstration

- The exact **2:50** sequence, words and captions are in `docs/submission/VIDEO-SHOTLIST.md`; it includes the live LinuxONE terminal, ward, phone alert, cut-off and Undo, CERT-In draft, containers and model results.
- The repeatable event order comes from `docs/spec/12-ward-script.md`; the screen routes are defined in `web/src/App.tsx`.
- The video states the honest limit: a laboratory prototype replaying recordings, not a clinical device (`docs/README-final-draft.md`).
- Final ward runs F1–F3 (build `f7fef1c`, agents on): beds 12/12, 11/12, 11/12 (B12's weak second sender seen in 1 of 3 runs); median time-to-safe B06 3.1 s, B07 19.2 s, B05 23.2 s, B10 23.2 s; 11 nurse alerts per run; Telegram 22 sent, 25–26 edited, 0 failed per run; B03 alert acknowledged at ladder step 2 after 44.6 / 47.4 / 46.5 s; IBM Granite briefing in all three (`docs/evidence/WARD-RUN.md`).
- **TODO(lead): upload the final video, insert its URL, and verify the submitted repository link and title `[TessNova_IBM Z Datathon 2026 Project]`.**
