# ml_v2: M2 "is this monitor alarm real?" (17 Oct 2026)

New code, written on build day; it does not use or copy `ml/`.

- `data/extract_vtac.py`: runs on the TEST LinuxONE; streams the 5,037 labelled VTaC events out of the zip and keeps 288–302 s at 250 Hz (alarm at 300 s).
- `m2gbt/prep.py`: runs on the BUILD LinuxONE; rebuilds the exact live window with `sw_data`: lead II (else the first ECG lead), PLETH, ABP/ART, −32768 → missing, gap-safe resampling to 125 Hz, simulator rounding, record seconds 290–300.
- `m2gbt/features.py`: 97 features, numpy/scipy only. They cover ECG beats (energy QRS detector), RR statistics, longest gaps, QRS width, template correlation, VF-band/spectral/morphology features, PPG and ABP pulses, ECG-vs-pulse agreement, signal quality and the alarm type. The same function is used for training and in the live brain.
- `m2gbt/train.py`: locks the held-out set first, runs grouped 5-fold CV, tunes per-type thresholds for the 2015 challenge score, and evaluates once with bootstrap CIs. It then exports the model.
- `m2gbt/model.py`: exports a sklearn `HistGradientBoostingClassifier` (trained on s390x, sklearn 1.4.1) to JSON. The numpy predictor is hash-checked before parsing; parity with sklearn is 0.0 max abs diff.
- `m2gbt/e2e_check.py`: replays held-out 2015 records through `BrainService` on LinuxONE.
- `stretch/cnn_nnpa.py`: a 1D-CNN that trains on CPU and runs inference on the z17 NNPA (`torch_nnpa`). It is not deployed because the tree beats it.
- `artifacts/m2_gbt_2026-10-17.json`: the deployed model. Its SHA-256 is pinned in `brain/sw_brain/m2gbt.py`.
- `results/`: `cv.json`, `heldout.json` (all held-out metrics), `e2e_check.json`, `cnn_result.json` and logs.

Reproduce on the build server (`~/sw/.venv`, `nice -n 15`, `OMP_NUM_THREADS=2`):

```sh
python -m m2gbt.prep <challenge-2015/training> vtac_prealarm.npz windows.npz
python -m m2gbt.train windows.npz out/
PYTHONPATH=<repo>/brain:<repo>/common:<repo>/ml_v2 python -m m2gbt.e2e_check <challenge-2015/training> out/
```
