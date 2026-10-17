# M2 "is this alarm real?" model — results

Every number below is read from `ml_v2/results/heldout.json` (1-lead), `ml_v2/results/heldout2.json` (2-lead, deployed) and `ml_v2/results/cnn_result.json` (NNPA CNN, live as a shown-only second opinion).

## Data and split
- PhysioNet/CinC Challenge 2015 (all 750 training records) + VTaC (5,037 labelled ventricular-tachycardia alarms).
- Held-out set locked before any training: 188 CinC records (74 true alarms) + the official VTaC test split (482 events, 137 true).
- Training: the other 5,117 windows, StratifiedGroupKFold(5) grouped by record (no record in two folds).
- Input = the same 10-second, 125 Hz pre-alarm window the live brain sees (ECG, pulse, arterial line when present).
- Trained natively on IBM LinuxONE (s390x, scikit-learn 1.4.1); served by the brain as numpy-only trees, SHA-256 pinned.

## Held-out results (score = (TP+TN)/(TP+TN+FP+5·FN), the Challenge 2015 metric; 95% bootstrap CI)

| Model | CinC 2015 score | CinC TPR / TNR | CinC AUROC | VTaC score | VTaC TPR / TNR | VTaC AUROC |
|---|---|---|---|---|---|---|
| Old live rule (baseline) | 0.391 [0.318, 0.484] | 0.459 / 0.895 | 0.677 | 0.336 [0.272, 0.412] | 0.073 / 0.936 | 0.505 |
| M2 1-lead trees (`M2-gbt-2026-10-17`) | 0.784 [0.690, 0.878] | 0.932 / 0.825 | 0.965 | 0.759 [0.702, 0.813] | 0.971 / 0.710 | 0.942 |
| **M2 2-lead trees (`M2-gbt2-2026-10-17`, live)** | **0.862 [0.785, 0.931]** | 0.973 / 0.851 | 0.968 | **0.832 [0.775, 0.885]** | 0.956 / 0.841 | 0.964 |
| 1D-CNN on the z17 NNPA (live second opinion, shown only, never decides) | 0.623 | 0.811 / 0.807 | 0.881 | 0.665 | 0.796 / 0.829 | 0.883 |

Per alarm type, 2-lead (CinC held-out, `heldout2.json`): ASYSTOLE 0.714, BRADY 0.778, TACHY 0.943 (TNR 0: the 2 false TACHY alarms were missed), VFIB 0.929, VTACH 0.906.

## Alarm fatigue at the live thresholds (advice only)
Recomputed from the two JSON files by `ml_v2/results/fatigue.py` (output: `raw/fatigue.txt`; it also checks that the thresholds in the JSON equal the deployed artifacts: `True` for both). M2 never silences anything: the monitor alarm still sounds, nothing is suppressed, delayed or downgraded; M2 only labels the alarm "likely false" or "likely real".

| Live 2-lead trees | False alarms marked likely-false | True alarms missed (marked likely-false) |
|---|---|---|
| CinC 2015 held-out (188) | **85.1%** (97/114) | **2.7%** (2/74) |
| VTaC test (482) | **84.1%** (290/345) | **4.4%** (6/137) |

Per alarm type, CinC held-out, 2-lead: ASYSTOLE 80.0% (20/25) likely-false, 16.7% (1/6) missed; BRADY 90.9% (10/11), 8.3% (1/12); TACHY 0.0% (0/2), 0.0% (0/33); VFIB 92.3% (12/13), 0.0% (0/1); VTACH 87.3% (55/63), 0.0% (0/22). 1-lead fallback: CinC 82.5% (94/114) / 6.8% (5/74), VTaC 71.0% (245/345) / 2.9% (4/137). Counts are small per type; a "missed" true alarm still sounded on the monitor.

Artifact pins: 1-lead SHA-256 `cc59fc61…2348` (97 features, 200 trees); 2-lead `72daa84b…2f75` (134 features, 200 trees). The brain uses the 2-lead model when the second ECG lead is at least half present, else the 1-lead model, else the live rule.

## Honest limits
- Small per-type held-out sets (VFIB has 1 true alarm): wide confidence intervals.
- CinC 2015 has no patient IDs, so record = group.
- Thresholds are tuned for the Challenge's 5×cost on missed true alarms, so specificity is modest.
- The score only explains an alarm: it never suppresses, delays or downgrades a monitor alarm (tested in `brain/tests`).
- The 2015 Challenge winners (81.39) used a hidden test set, 2 leads at 250 Hz and 5 minutes of data: not directly comparable.
- Robustness (same held-out windows, perturbed; `ROBUSTNESS.md`, `ml_v2/results/robustness.json`): mild noise/mains/gain/≤1 s shift stay within the clean CI; worst for missed alarms is SNR 10 dB (CinC TPR 0.784); a forged calm pulse under a real ECG fools M2 (VTaC TPR 0.591), which is why forgery is M3/M4/M5's job and M2 never suppresses an alarm.

## IBM Z: Telum II on-chip AI (live second opinion)
The 1D-CNN now runs live on the z17's on-chip AI accelerator (NNPA, `torch_nnpa 1.5.0`, device `nnpa:0`) as a second opinion. For every bed alarm the live brain scores with M2, it scores the same 10 s window (125 Hz ECG + PPG, + ABP when present) and publishes its own "is this alarm real?" probability on `ward/chip/<bed>`. It is shown only: it never changes a verdict, an alert or an action, and its hub account may only read vitals and publish on `ward/chip/+`. The deployed M2 stays the trees.

- Model: `chip/model/cnn_state.pt`, SHA-256 `c7ad2efe8dfb475619e336d437e1d4df4aaa3290470bec777f9a4894a571f1c6`, retrained on LinuxONE with the unchanged `ml_v2/stretch/cnn_nnpa.py`: best epoch 7, same thresholds, all 670 held-out scores identical to `cnn_result.json` (max |diff| 0.0).
- Held-out: CinC 2015 score 0.623, VTaC 0.665, below the live trees (0.862 / 0.832). That is why it is a second opinion, not M2.
- Live code path, 670 held-out windows one at a time: max |NNPA − CPU training| 0.0018, labels agree 670/670. Ward replay: chip windows = brain M2 windows (3/3: B03 VTACH, B04 ASYSTOLE, B07 VFIB).
- Live proof (demo run `run_20261017_172415`, start 270, `mosquitto_sub ward/chip/+` on the hub): B03 VTACH p 0.769 real, B04 ASYSTOLE p 0.166 false, B07 VFIB p 0.953 real, all `nnpa:0`; 0 hub denials. Acceptance 7/7 with the chip connected; security live test 15/15 (default `--tls-host 127.0.0.1`).

| Per-alarm CNN (scaling + forward, batch 1, 1 thread, z17) | n | median ms | p95 ms |
|---|---|---|---|
| nnpa:0, 670 held-out windows | 670 | 2.11 | 2.46 |
| cpu, 670 held-out windows | 670 | 1.86 | 2.18 |
| nnpa:0, ward alarm windows ×20 | 60 | 2.21 | 2.46 |
| cpu, ward alarm windows ×20 | 60 | 1.98 | 2.30 |
| nnpa:0, live over TLS (3 alarms) | 3 | 8.13 | 29.96 (max) |

Honest: at batch 1 this small CNN is not faster on the NNPA than on one CPU core (about 0.25 ms slower); both are about 0.05% of the 5 s tick. Where it runs: the TEST LinuxONE z17 guest, inside IBM's lab container (`notebook`, torch 2.11 + torch_nnpa 1.5.0) as `sw-chip.service` (Restart=always), connected to the hub on the BUILD guest over TLS 8883 as hub user `chip`. One message per alarm episode. Sources: `chip/README.md`, `chip/results/` (bench, parity, `live/chip-live-proof.txt`, `live/acceptance.md`), `ml_v2/results/cnn_result.json`.

### Batched, at ward scale (does the NNPA help with many beds?)
Measured 18 Oct 2026 on the TEST z17 guest (2 vCPUs) inside the `notebook` container (torch 2.11, torch_nnpa 1.5.0), with `sw-chip.service` left running, by `python -m sw_chip.batch_bench` (bench only; the live service still scores one alarm at a time). Same pinned CNN; each call = input scaling (numpy, on the CPU for both) + host→device + forward + sigmoid + device→host. Real held-out windows (670), 30 warm-up + 200 timed calls per row. The model's parameters and conv outputs are on `nnpa:0` (checked); we did not profile which individual ops the NNPA runs.

| Batch | Threads | cpu median / p95 ms | nnpa:0 median / p95 ms | cpu windows/s | nnpa:0 windows/s | nnpa ÷ cpu (median) |
|---|---|---|---|---|---|---|
| 1 | 1 | 1.71 / 2.04 | 1.98 / 2.43 | 586 | 506 | 1.16 |
| 4 | 1 | 4.81 / 6.02 | 5.40 / 6.23 | 832 | 741 | 1.12 |
| 12 | 1 | 12.9 / 13.9 | 14.5 / 17.1 | 930 | 829 | 1.12 |
| 32 | 1 | 33.5 / 36.1 | 37.4 / 47.4 | 955 | 855 | 1.12 |
| 96 | 1 | 99.4 / 108.5 | 118.3 / 135.8 | 966 | 812 | 1.19 |
| 256 | 1 | 287.3 / 297.4 | 335.9 / 380.1 | 891 | 762 | 1.17 |
| 1 | 2 | 1.58 / 2.36 | 1.89 / 2.91 | 634 | 530 | 1.20 |
| 4 | 2 | 3.80 / 6.04 | 4.34 / 6.37 | 1,052 | 922 | 1.14 |
| 12 | 2 | 9.18 / 11.5 | 10.7 / 18.7 | 1,307 | 1,117 | 1.17 |
| 32 | 2 | 22.9 / 27.0 | 25.6 / 36.4 | 1,398 | 1,250 | 1.12 |
| 96 | 2 | 70.5 / 93.3 | 74.0 / 97.2 | 1,362 | 1,297 | 1.05 |
| 256 | 2 | 231.2 / 285.3 | 245.8 / 302.7 | 1,107 | 1,042 | 1.06 |

Whole-ward pattern: 96 beds' current 10 s windows (cut from the 12 real ward packs, 8 offsets each, moving 5 s per tick) scored in one batch every 5 s, 12 ticks (60 s) per row:

| 96 beds, one batch / 5 s | median ms | max ms (12 ticks) | CPU s per tick (median) | process CPU, % of the 2-vCPU guest |
|---|---|---|---|---|
| cpu, 1 thread | 102.7 | 108.4 | 0.103 | 1.03 |
| nnpa:0, 1 thread | 116.0 | 124.4 | 0.116 | 1.17 |
| cpu, 2 threads | 89.6 | 151.0 | 0.111 | 1.21 |
| nnpa:0, 2 threads | 89.1 | 124.6 | 0.127 | 1.29 |

Parity on all 670 held-out windows at every batch size: max |nnpa − cpu| 0.0018 (mean 0.00023), the same as at batch 1.

Honest: on this guest the NNPA is not faster than the CPU at any batch size tested (1 to 256), with 1 or 2 threads: its median is 5–20% slower, and there is no crossover batch size in this range. At 96 beds in one batch with 2 threads the two medians are within 0.5 ms (89.1 vs 89.6 ms), a tie. The NNPA run also does not leave more CPU for the brain: the calling process is busy for the whole call (0.127 vs 0.111 CPU s per tick). Either way, scoring every bed every 5 s costs about 1.2% of the 2-vCPU guest and at most 3.1% of the tick. For this small CNN the on-chip AI is a working, numerically matched second device, not a speed-up. Source: `chip/results/batch_bench.json` (+ `batch_bench.log`), `chip/sw_chip/batch_bench.py`.
