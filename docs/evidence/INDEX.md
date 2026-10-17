# Evidence index (what proves what)

| Judging area | Proof |
|---|---|
| Problem + data | `ML-RESULTS.md` (PhysioNet/CinC 2015, VTaC; held-out split), `docs/spec/12-ward-script.md` (12 real patient recordings) |
| Solution works (accuracy, safety) | `ML-RESULTS.md` (M2 0.862 / 0.832 vs old rule 0.391 / 0.336), ward-run results (`WARD-RUN.md`), screens below |
| IBM Z use (containers, security, scalability, compute) | `PLATFORM.md` (z17, Telum II nnpa, z/VM), `CONTAINERS.md`, `SECURITY.md` (15/15 live), `SCALE.md` (96 beds per brain), `RESOURCES.md`, NNPA CNN in `ML-RESULTS.md` |
| Responsible design | `SECURITY.md` (undo on every cut-off, cut-off never hides a real alarm), `ML-RESULTS.md` limits, brain README (alarms never suppressed) |

Screens (`screens/`): 01 live ward mid-run · 02 bed B05 under tampering with the six checks · 03 security cut-offs + fleet hunt · 04 action log with Undo · 05 census trust column · 06 alert escalation ladder · 07 B03 VTACH with the M2 score · 08 B06 emergency on a cut-off monitor · 09 incident timeline with SHA-256 evidence · 10 CERT-In report draft.
