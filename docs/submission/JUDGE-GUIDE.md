# Judge guide

## Criterion 1 — value and theme

- SentinelWard separates a patient emergency, a faulty sensor and forged monitor data, while enforcing “never blank” and “tampering never cancels an emergency.” Proof: `docs/ARCHITECTURE.md`; live screens: **Ward** and **Bed** (`web/src/pages/Ward.tsx`, `web/src/pages/Bed.tsx`).
- The lab ward replays open ICU recordings from PhysioNet/CinC, VTaC, MIMIC-III and VitalDB. Proof: `docs/OPEN-SOURCE.md`; bed-by-bed demo sources: `docs/spec/12-ward-script.md`.
- Twelve monitors publish once per bed per second into six checks and a decision layer (`docs/spec/00-contract-v1.2.md`). The checked-in LinuxONE run shows live telemetry and verdicts (`deploy/evidence/demo-watch.md`).
- A real VT alarm reached `EMERGENCY` in **3.019 s** and the ward API in **3.139 s** (`deploy/evidence/smoke-h6-checkpoint1.md`).

## Criterion 2 — originality and implementation

- The live brain implements M1–M6, bounded windows, model fallback and the eight-verdict safety precedence. Proof: `brain/README.md`.
- The two-lead M2 model, training pipeline and portable hash-checked inference were written on build day. Proof: `ml_v2/README.md`; model artifact and metrics: `ml_v2/results/heldout2.json`.
- A1–A8 cover alert escalation, cut-off and Undo, SHA-256 evidence, fleet hunt, CERT-In draft, biomed tickets, workload and IBM Granite briefing. Proof: `agents_v2/REPORT.md`; screens: **Security**, **Incidents**, **CERT-In report draft**, **Repair tickets**, **Briefing and workload**.
- Open-source software, model tooling and datasets are linked and attributed in `docs/OPEN-SOURCE.md`.

## Criterion 3 — IBM LinuxONE design and evidence

- Platform evidence shows `s390x`, machine type **9175**, IBM z/VM and the `nnpa` CPU feature (`deploy/evidence/lscpu.txt`, `deploy/evidence/proc-sysinfo.txt`, `deploy/evidence/nnpa-cpuinfo.txt`).
- M2 training results record host `tessnovabuild`, machine `s390x`, held-out CiNC score **0.862** and VTaC VT score **0.832** for the two-lead model (`ml_v2/results/heldout2.json`). The separate CNN records NNPA availability and `nnpa:0` inference (`ml_v2/results/cnn_result.json`).
- The hardened six-container design uses non-root users, read-only filesystems, dropped capabilities and resource limits (`deploy/containers/README.md`, `deploy/containers/compose.yaml`). **TODO(lead): capture a readable live `docker ps` plus hardening evidence screenshot.**
- The secured hub design uses TLS, deny-by-default ACLs and per-device identities (`security_v2/SECURITY.md`). **TODO(lead): run the LinuxONE live security test and capture its PASS table.**
- Existing process snapshots cover live ward load (`deploy/evidence/ps-top-11beds-T0430.txt`, `deploy/evidence/ps-top-10beds-T1000.txt`). **TODO(lead): capture `docker stats` and the scale-test result for the final scalability screenshot.**

## Criterion 4 — clarity and live demonstration

- The exact **2:50** sequence, words and captions are in `docs/submission/VIDEO-SHOTLIST.md`; it includes the live LinuxONE terminal, ward, phone alert, cut-off and Undo, CERT-In draft, containers and model results.
- The repeatable event order comes from `docs/spec/12-ward-script.md`; the screen routes are defined in `web/src/App.tsx`.
- The video states the honest limit: a laboratory prototype replaying recordings, not a clinical device (`docs/README-final-draft.md`).
- **TODO(lead): record and verify a real emergency alert arriving on the Telegram phone; checked-in evidence currently says NOT RUN (`deploy/evidence/smoke-h6-checkpoint1.md`).**
- **TODO(lead): upload the final video, insert its URL, and verify the submitted repository link and title `[TessNova_IBM Z Datathon 2026 Project]`.**
