# Evidence index (what proves what)

| Judging area | Proof |
|---|---|
| Problem + data | `ML-RESULTS.md` (PhysioNet/CinC 2015, VTaC; held-out split), `docs/spec/12-ward-script.md` (12 real patient recordings) |
| Solution works (accuracy, safety) | `ML-RESULTS.md` (M2 0.862 / 0.832 vs old rule 0.391 / 0.336), final ward runs F1–F3 (`WARD-RUN.md`: 12/12, 11/12, 11/12; 11 nurse alerts per run), screens below |
| Alarm fatigue (advice only, nothing suppressed) | `raw/fatigue.txt` from `ml_v2/results/fatigue.py`: at the live thresholds 85.1% of false CinC held-out alarms marked likely false, 2.7% of true missed; VTaC 84.1% / 4.4% (`ML-RESULTS.md`) |
| IBM Z use (containers, security, scalability, compute) | `PLATFORM.md` (z17, Telum II nnpa, z/VM), `CONTAINERS.md`, `SECURITY.md` (15/15 live), `SCALE.md` (96 beds per brain), `RESOURCES.md`, NNPA CNN in `ML-RESULTS.md` |
| Telum II on-chip AI, live | `ML-RESULTS.md` "IBM Z: Telum II on-chip AI": CNN second opinion on `nnpa:0` for every M2-scored alarm (shown only), SHA-256 pinned, NNPA vs CPU latency, live `ward/chip/+` proof (`chip/results/live/`) |
| Telum II at ward scale (batched) | `ML-RESULTS.md` "Batched, at ward scale": batch 1–256 and a 96-bed batch every 5 s, nnpa:0 vs cpu; NNPA not faster at any tested batch size (`chip/results/batch_bench.json`) |
| Responsible design | `SECURITY.md` (undo on every cut-off, cut-off never hides a real alarm), `ML-RESULTS.md` limits, brain README (alarms never suppressed) |

Screens (`screens/`): 01 live ward mid-run · 02 bed B05 under tampering with the six checks · 03 security cut-offs + fleet hunt · 04 action log with Undo · 05 census trust column · 06 alert escalation ladder · 07 B03 VTACH with the M2 score · 08 B06 emergency on a cut-off monitor · 09 incident timeline with SHA-256 evidence · 10 CERT-In report draft · 11 B03 VTACH with the AI-chip second opinion (VTACH, 77% real, `nnpa:0`, 6.04 ms; run 270, 17 Oct 23:21) · 12 ward with the chip icon on B03's tile · 13 B03 chip panel empty state before the alarm.
