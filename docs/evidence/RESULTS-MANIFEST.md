# Claim manifest — 18 Oct 2026

Saved evidence, not a new live run. Do not combine cohorts or infer clinical benefit.

| Claim | Cohort and exact evidence | Limit |
|---|---|---|
| 12/12 bed checks; B12 UNSURE 17:04, NORMAL 17:59 | N, build `4348467`: `raw/wardrun-night/judgeN.txt`, `timeline_verdictsN.txt` | One post-fix run. F1/F2/F3: 12/11/11 of 12; B12 seen only in F1 (`raw/wardrun-final/timeline_verdictsF1.txt`, `timeline_verdictsF2.txt`, `timeline_verdictsF3.txt`). |
| Time-to-safe B05/B06/B07/B10 | N: 21.2/1.2/21.3/21.2 s (`raw/wardrun-night/metricsN.txt`). F1–F3 medians: 23.2/3.1/19.2/23.2 s (`raw/wardrun-final/metricsF1.txt`, `metricsF2.txt`, `metricsF3.txt`) | Scripted attack start → bed untrusted AND nurse told AND device cut off. B06 is forged flatline; B07 is real VF during a hack. |
| Likely-false advice / true-alarm misses | CinC held-out: 85.1% (97/114) / 2.7% (2/74); VTaC test: 84.1% (290/345) / 4.4% (6/137). `raw/fatigue.txt`, `ml_v2/results/heldout2.json` (repo root) | Classification only; alarms remain active. No all-alarm or workload-reduction claim. |
| Chip coverage | N: B03/B04/B07 scored, B06 forged ASYSTOLE not scored; 3 chip messages vs 4 M2 episodes (`raw/wardrun-night/chip_check.txt`) | Scores alarms it receives in time; not guaranteed for every alarm. Shown only. |
| Witness sender counts | N B12 reported multiple publishers (`raw/wardrun-night/timeline_verdictsN.txt`); extractor: `security_v2/sw_sec/features.py::log` (repo root) | Distinct broker client IDs per bed topic/window, not cryptographic identity of each frame. |
| 96-bed brain scale | Later 3-minute summary in `SCALE.md`; cited raw tick logs not bundled | Older `raw/containers/scale-stats.txt` rejected all 5,220 extra-bed messages; current `SW_BRAIN_MAX_BED` permits extending the accepted range. No 96-bed soak. |
| B07 blank-after-data | 88 API samples in each of N and F1–F3 (`raw/wardrun-night/metricsN.txt`, `raw/wardrun-final/metricsF1.txt`, `metricsF2.txt`, `metricsF3.txt`) | Not a screen measure. Exact counter script and polls not bundled; nurse-visible continuity unknown. See `WARD-RUN.md`. |
| A3 sealed evidence | `agents_v2/sw_agents/agents/a3_evidence.py` (repo root); digests in `raw/wardrun-night/timeline_agentsN.txt` | Up to 10 minutes of buffered verdict/score/event messages at incident opening, not raw waveforms; payloads not bundled. |
