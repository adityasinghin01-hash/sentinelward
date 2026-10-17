# M2 robustness and model security

M2 is the live "is this alarm real?" trees (`M2-gbt2-2026-10-17`, 1-lead `M2-gbt-2026-10-17` fallback). This page shows how its held-out results change when the signal is damaged or forged, and what happens when its model file is tampered with. Every number comes from `ml_v2/results/robustness.json` (log: `ml_v2/results/robustness.log`) and `brain/tests/test_m2_integrity.py`.

## How it was measured
- Data: the same 670 held-out windows as `heldout2.json` (188 CinC 2015 records, 74 true; 482 VTaC events, 137 true), locked before training. Nothing was trained or re-tuned. The deployed per-type thresholds were used.
- Code path: each window goes through the brain's real `EmergencyDetector`, with the SHA-256-pinned artifacts and the brain's own fallback order (2-lead if `ecg2` is at least half present, else 1-lead, else the live ECG rule). A window where no advice is possible counts as "predicted real", because the alarm stands.
- Run on the LinuxONE build server (s390x, Python 3.12.3, numpy 1.26.4, the trees' training stack), 132 s, seed `20261018`. Every random part is seeded per (condition, window), so the run is reproducible: `python -m robustness.run <windows_v13.npz> <heldout_mask.npy> <heldout_shift.npz> <out.json> [heldout_scores2.npz]` from `ml_v2/`.
- Parity check: the clean run gives the published 0.862 / 0.832, and its scores match the training run's held-out scores to within 0.0002. The one remaining difference is a window whose second lead is entirely empty. Training scored it with the 2-lead model, while the brain correctly uses the 1-lead model.
- Time shift moves the window earlier, rebuilt from the original recordings by `ml_v2/robustness/prep_shift.py`. Shift 0 must reproduce the training windows exactly, and `run.py` asserts that it does.
- The values are rounded the way the simulator sends them (ECG 3, PPG 2, ABP 1 decimals).

Score = (TP+TN)/(TP+TN+FP+5·FN), the Challenge 2015 metric. TPR = true alarms called real, TNR = false alarms called false. "Flipped" counts true alarms called real on clean data and "likely false" after the change.

| Condition | Strength | CinC score | TPR | TNR | AUROC | VTaC score | TPR | TNR | AUROC | True alarms flipped (CinC / VTaC) |
|---|---|---|---|---|---|---|---|---|---|---|
| **Clean** | - | **0.862** | 0.973 | 0.851 | 0.968 | **0.832** | 0.956 | 0.841 | 0.964 | 0 / 0 |
| White noise, all channels | SNR 30 dB | 0.891 | 0.987 | 0.860 | 0.969 | 0.838 | 0.956 | 0.849 | 0.959 | 0 / 0 |
| | SNR 20 dB | 0.768 | 0.905 | 0.868 | 0.966 | 0.786 | 0.898 | 0.870 | 0.952 | 5 / 9 |
| | SNR 10 dB | 0.639 | 0.784 | 0.903 | 0.954 | 0.701 | 0.781 | 0.913 | 0.942 | 14 / 25 |
| Baseline wander 0.15–0.5 Hz, ECG + PPG | 0.25× range | 0.797 | 0.919 | 0.886 | 0.968 | 0.754 | 0.876 | 0.855 | 0.948 | 5 / 11 |
| | 0.5× range | 0.773 | 0.905 | 0.877 | 0.965 | 0.779 | 0.890 | 0.870 | 0.947 | 6 / 10 |
| | 1× range | 0.802 | 0.919 | 0.895 | 0.963 | 0.737 | 0.832 | 0.896 | 0.940 | 5 / 18 |
| Powerline 50 Hz, ECG leads | 0.1× range | 0.872 | 0.973 | 0.868 | 0.966 | 0.809 | 0.934 | 0.844 | 0.961 | 1 / 3 |
| | 0.25× range | 0.878 | 0.973 | 0.877 | 0.969 | 0.819 | 0.934 | 0.858 | 0.956 | 1 / 3 |
| | 0.5× range | 0.833 | 0.946 | 0.877 | 0.970 | 0.792 | 0.898 | 0.878 | 0.953 | 3 / 9 |
| ECG amplitude scaling | ×0.25 | 0.837 | 0.973 | 0.807 | 0.971 | 0.803 | 0.934 | 0.835 | 0.955 | 1 / 4 |
| | ×0.5 | 0.865 | 0.987 | 0.816 | 0.972 | 0.813 | 0.942 | 0.838 | 0.961 | 0 / 2 |
| | ×2 | 0.855 | 0.960 | 0.877 | 0.968 | 0.825 | 0.942 | 0.855 | 0.957 | 1 / 2 |
| Second ECG lead dropout (end of window) | 30% missing (2-lead runs) | 0.759 | 0.919 | 0.816 | 0.959 | 0.790 | 0.942 | 0.803 | 0.946 | 4 / 5 |
| | 60% missing (→ 1-lead) | 0.784 | 0.932 | 0.825 | 0.965 | 0.759 | 0.971 | 0.710 | 0.942 | 3 / 3 |
| | 100% missing (→ 1-lead) | 0.784 | 0.932 | 0.825 | 0.965 | 0.759 | 0.971 | 0.710 | 0.942 | 3 / 3 |
| PPG dropout (end of window) | 30% | 0.820 | 0.960 | 0.816 | 0.966 | 0.826 | 0.949 | 0.844 | 0.958 | 1 / 1 |
| | 60% | 0.794 | 0.946 | 0.807 | 0.955 | 0.744 | 0.876 | 0.838 | 0.936 | 2 / 11 |
| | 100% | 0.816 | 0.973 | 0.772 | 0.959 | 0.783 | 0.964 | 0.756 | 0.955 | 0 / 0 |
| ABP dropout (end of window) | 30% | 0.850 | 0.960 | 0.868 | 0.960 | 0.829 | 0.964 | 0.823 | 0.961 | 1 / 0 |
| | 60% | 0.809 | 0.946 | 0.833 | 0.958 | 0.808 | 0.949 | 0.817 | 0.950 | 2 / 1 |
| | 100% | 0.872 | 0.973 | 0.868 | 0.966 | 0.812 | 0.949 | 0.823 | 0.955 | 0 / 1 |
| Time shift (alarm stamped late) | 0.5 s | 0.885 | 0.987 | 0.851 | 0.964 | 0.841 | 0.964 | 0.841 | 0.965 | 0 / 1 |
| | 1 s | 0.857 | 0.973 | 0.842 | 0.964 | 0.834 | 0.956 | 0.844 | 0.963 | 1 / 4 |
| | 2 s | 0.693 | 0.865 | 0.825 | 0.939 | 0.773 | 0.898 | 0.849 | 0.952 | 9 / 11 |
| Sample-hold flatline, all channels | 1 s segment | 0.708 | 0.987 | 0.553 | 0.930 | 0.614 | 0.949 | 0.530 | 0.910 | 0 / 5 |
| | 2 s | 0.625 | 0.987 | 0.412 | 0.914 | 0.567 | 0.985 | 0.414 | 0.894 | 1 / 0 |
| | 4 s | 0.543 | 1.000 | 0.246 | 0.856 | 0.463 | 0.993 | 0.258 | 0.816 | 0 / 0 |

What this shows:
- Mild damage costs little: SNR 30 dB, 50 Hz mains up to 0.25× range, ECG gain ×0.5 to ×2, a 0.5–1 s timing error and a lost ABP line all stay within the clean 95% interval (CinC [0.785, 0.931], VTaC [0.775, 0.885]).
- When the second lead is lost, the brain drops to the 1-lead model, and the result is exactly the published 1-lead result (0.784 / 0.759). A second lead that is only 30% missing still uses the 2-lead model and scores slightly worse (0.759 CinC). That is a known edge of the 50% switch-over rule.
- Heavy noise (SNR 10 dB) and a 2 s timing error are the worst cases for missing true alarms: CinC TPR 0.784 / 0.865, i.e. 14 and 9 true alarms newly scored "likely false".
- Flatline segments mostly push M2 toward "real": TPR is 0.949–1.000 while TNR falls as low as 0.246. This gives the lowest scores (4 s: 0.543 / 0.463). True-alarm advice errors remain: the 1 s VTaC condition newly flips 5 true alarms to likely false. These are classification results, not a safety guarantee.
- In the tested damage conditions above, the lowest AUROC is 0.816 (4 s flatline, VTaC). This is an offline ranking result, not evidence of clinical safety.

## Forged input: real ECG, fake pulse
This is what an attacker who controls the PPG/ABP stream, but not the ECG, could feed in.

| Forgery | CinC score | TPR | TNR | VTaC score | TPR | TNR | True alarms flipped (CinC / VTaC) |
|---|---|---|---|---|---|---|---|
| PPG+ABP copied from another patient (random donor) | 0.625 | 0.797 | 0.842 | 0.612 | 0.723 | 0.838 | 13 / 32 |
| PPG+ABP copied from a false-alarm window (calm pulse) | 0.575 | 0.730 | 0.877 | 0.528 | 0.591 | 0.846 | 18 / 50 |
| Own PPG+ABP shifted 2 s (circular) | 0.852 | 0.973 | 0.833 | 0.826 | 0.956 | 0.832 | 0 / 0 |
| Own PPG+ABP shifted 5 s (circular) | 0.857 | 0.973 | 0.842 | 0.812 | 0.949 | 0.823 | 0 / 1 |

Yes, M2 alone can be fooled. A calm pulse pasted under real VT newly flips 50 of 137 true VTaC alarms to "likely false"; with the 6 clean misses, 56/137 are marked likely false (TPR 0.591). This is expected, because pulse/ECG agreement is one of M2's strongest features. A shifted copy of the patient's own pulse does not fool it, since the rate still agrees.

M2 advice does not suppress, delay or downgrade an active monitor alarm (`brain/tests/test_m2_gbt.py::test_low_probability_cannot_suppress_or_downgrade_alarm`); misleading advice can still affect a reader. The following tests demonstrate other checks on specific forged or mixed signals, not a full-pipeline evaluation of every forgery above:
- M3 (do heartbeat and pulse agree for this patient): `brain/tests/test_m3_real_packs.py::test_b11_ecg_with_any_other_real_pulse_still_scores_high` (another patient's real pulse under B11's ECG, 7 donors), `test_frozen_pulse_cannot_outwait_replay_hold`, `test_sustained_pulse_shift_cannot_train_itself_away`, and `test_m3_applicability.py::test_irregular_forged_ppg_cannot_pause_a_regular_ecg`.
- M4/M5 (replay, second sender, flood) and the decision layer: `brain/tests/test_attack_transport.py` (e.g. `test_b07_flood_then_paced_sender_is_tampering_and_alarm_is_both`, `test_waveform_replay_remains_independent_evidence`) and `brain/tests/test_attack_live_inputs.py`. The second file drives the offline ward attack replay `tests_system/attack_replay_eval.py`, which uses the production pack building, attack sender and network-witness extractor.
- Live: the 20-minute ward run (`WARD-RUN.md`): B05 replay → TAMPERING, B07 real VFIB during an attack → BOTH. Hub per-device accounts (`SECURITY.md`) block cross-bed publishing with another monitor account; a stolen valid credential can still forge its own bed. The demonstration attacker uses an exempt account (`security_v2/SECURITY.md`).

## Model security (`brain/tests/test_m2_integrity.py`, 55 tests, all pass)
- Tampered artifact bytes (one bit flipped, whitespace only, a poisoned leaf value) or the 2-lead file swapped in for the 1-lead one cause a SHA-256 mismatch. The model is not loaded (the hash is checked before parsing), the live ECG rule explains the alarm, and the alarm stays EMERGENCY / high.
- A missing file, and content that passes the hash but is broken (truncated, garbage, empty, wrong format, not an object, a tree indexing a feature that does not exist, a missing threshold for an alarm type), all fall back to the live rule. Every case is checked for an EMERGENCY verdict.
- A model that returns NaN is refused as an "invalid probability". ±inf / huge leaf values still give a probability in [0, 1].
- Hostile inputs (NaN everywhere, inf spikes, −inf, ±1e300, all null, constant, short signal) on every channel combination × 5 alarm types: no crash, and the score is always in [0, 1] or "unavailable".
- Vitals messages with NaN/inf samples are refused at the input contract, and the alarm still gives EMERGENCY. An M2 adapter that throws an exception cannot stop the tick.
- "Logged" means the reason is kept in `GbtM2.failure` and published on `ward/bed/<bed>/score/M2` as `extra.gbt.extra.unavailable_reason`, which the backend stores. There is no separate log line.
- Existing tests in `test_m2_gbt.py` already cover the pinned digests, the 2-lead → 1-lead fallback and the case where both artifacts are tampered.
- Full brain suite after adding these tests: 380 passed (local Mac, Python 3.12).

## Honest limits
- Offline and on held-out windows only. These are synthetic perturbations of real recordings, not new recordings of noisy or failing sensors, and none of this was measured in the live ward.
- Small sets per alarm type (VFIB has 1 true alarm in CinC held-out). There are no confidence intervals for the perturbed runs, so differences within the clean 95% interval (e.g. SNR 30 dB scoring above clean) are noise.
- One seed and one random draw per window. Perturbation strengths are our own choices, not a clinical standard.
- Forgery was tested only on the pulse channels. A forged ECG is M1/M3/M4/M5's job and was not run through M2 here.
- The run must use the training stack. The same script on a Mac (x86-64, scipy 1.18 instead of 1.11.4) scored 24 of 670 clean windows more than 0.001 differently (max 0.25), so all numbers above come from the LinuxONE run. A brain on a different numeric stack would see the same small drift.
