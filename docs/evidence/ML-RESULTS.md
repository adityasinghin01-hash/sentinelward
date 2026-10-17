# M2 "is this alarm real?" model — results

Every number below is read from `ml_v2/results/heldout.json` (1-lead), `ml_v2/results/heldout2.json` (2-lead, deployed) and `ml_v2/results/cnn_result.json` (NNPA CNN experiment).

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
| 1D-CNN on the z17 NNPA (not deployed) | 0.623 | 0.811 / 0.807 | 0.881 | 0.665 | 0.796 / 0.829 | 0.883 |

Per alarm type, 2-lead (CinC held-out, `heldout2.json`): ASYSTOLE 0.714, BRADY 0.778, TACHY 0.943 (TNR 0: the 2 false TACHY alarms were missed), VFIB 0.929, VTACH 0.906.

Artifact pins: 1-lead SHA-256 `cc59fc61…2348` (97 features, 200 trees); 2-lead `72daa84b…2f75` (134 features, 200 trees). The brain uses the 2-lead model when the second ECG lead is at least half present, else the 1-lead model, else the live rule.

## Honest limits
- Small per-type held-out sets (VFIB has 1 true alarm): wide confidence intervals.
- CinC 2015 has no patient IDs, so record = group.
- Thresholds are tuned for the Challenge's 5×cost on missed true alarms, so specificity is modest.
- The score only explains an alarm: it never suppresses, delays or downgrades a monitor alarm (tested in `brain/tests`).
- The 2015 Challenge winners (81.39) used a hidden test set, 2 leads at 250 Hz and 5 minutes of data: not directly comparable.

## IBM Z: Telum II on-chip AI
The 1D-CNN ran on the z17's on-chip AI accelerator (NNPA, `torch_nnpa 1.5.0`, device `nnpa:0`): 670 held-out windows in 0.41 s, max |NNPA − CPU| difference 0.0018 (fp16). It scored below the trees, so the trees are deployed; the NNPA path is proven and ready for a larger model. Source: `.work/kiro-ml-REPORT.md`, `ml_v2/results/cnn_result.json`.
