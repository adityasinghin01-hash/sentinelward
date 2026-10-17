# chip/: AI-chip second opinion (IBM z17 Telum II NNPA)

Written 17 Oct 2026. For each bed alarm that the live brain scores with M2, this service runs
the stretch 1D-CNN (`ml_v2/stretch/cnn_nnpa.py`) on the z17 on-chip AI accelerator
(`torch_nnpa`, device `nnpa:0`). It then publishes its own "is this alarm real?" probability.
The result is **shown only**. The service subscribes to `ward/bed/+/vitals` and publishes only
on `ward/chip/<bed_id>`, and its hub account cannot publish anything else. It never changes a
verdict, an alert or an action. The deployed M2 stays the gradient-boosted trees.

## Message (`ward/chip/<bed_id>`, QoS 1, not retained)
```json
{"v":1,"bed_id":"B03","ts":1792253764000,"alarm_code":"VTACH","p_real":0.7694,"label":"real",
 "threshold":0.211,"model":"M2-cnn-nnpa-2026-10-17","device":"nnpa:0","latency_ms":3.96,
 "heldout_challenge_cinc":0.623,"heldout_challenge_vtac":0.665}
```
- `ts` is the first alarmed frame (the alarm onset the brain uses).
- `label` is `real` when `p_real >= threshold`. The threshold is the CNN's own per-alarm-type
  threshold, tuned on validation for the Challenge 2015 score. TACHY's threshold is 0.0, so a
  TACHY alarm is always labelled `real`.
- `device` is `nnpa:0`, or `cpu` when torch_nnpa or the accelerator is missing.
- `latency_ms` covers input scaling plus the forward pass on the device.

## Same window as the brain
`sw_chip/tracker.py` copies `BrainService.receive`. When an alarm frame starts a new episode
and the 10 one-second chunks at ts−10 s … ts−1 s are contiguous, those 1,250 samples (125 Hz ECG,
PPG and, when present, ABP) are scored once. This is exactly when the trees score M2. Checked
with `sw_chip.bench --brain` on the packs-v13 ward replay (11,790 vitals): the chip windows and
the brain's M2 windows were identical (3/3). The client cannot see bedside `patient_ok` or demo
control messages (it has no right to read them). A demo restart is detected from the seq reset.

## Model
`model/cnn_state.pt`, SHA-256 `c7ad2efe8dfb475619e336d437e1d4df4aaa3290470bec777f9a4894a571f1c6`,
pinned in `sw_chip/model.py` and checked before loading. It was retrained by `sw_chip/retrain.py`,
which runs the unchanged `cnn_nnpa.py` (same windows, held-out mask and seed) on the TEST
LinuxONE. The best epoch, the thresholds and the held-out results (CinC 0.623, VTaC 0.665) are the
same as in `ml_v2/results/cnn_result.json`, and all 670 held-out scores match the original run
exactly (max |diff| 0.0). `sw_chip.parity` scores the 670 held-out windows one at a time through
the live code path: max |diff| vs training is 0.0018 on nnpa:0 and 1.2e-7 on cpu, and the labels
agree 670/670.

## Run
- Tests (CPU torch): `PYTHONPATH=chip python -m pytest chip/tests`
- Service: `PYTHONPATH=chip python -m sw_chip`. Settings come from environment variables:
  `SW_CHIP_HOST`, `SW_CHIP_PORT`, `SW_CHIP_USER`, `SW_CHIP_PASSWORD[_FILE]`, `SW_CHIP_CA` (turns
  on TLS), `SW_CHIP_DEVICE` (`nnpa`/`cpu`) and `SW_CHIP_CLIENT_ID`.
- Hub account: on BUILD, `sudo python security_v2/scripts/add_chip.py --server-ip 148.100.112.19
  --remote-ca /home/ibm-user/shared/chip/ca.crt`. It is idempotent, and `--remove` undoes it.
- TEST LinuxONE: `deploy/chip/install_test.sh` installs `sw-chip.service`. The unit runs
  `docker exec` into IBM's `notebook` container, with `Restart=always`, and is enabled at boot.
- Bench: `python -m sw_chip.bench <packs> simulator/ward_script.yaml out.json [--device cpu] --brain`
- Batched bench (optional, bench only; the live service is unchanged):
  `python -m sw_chip.batch_bench run --device nnpa|cpu --windows W.npz --mask M.npy --packs P --out X.json`,
  then `python -m sw_chip.batch_bench merge cpu.json nnpa.json results/batch_bench.json`.
  Result (18 Oct, TEST): NNPA not faster at any batch size 1–256; see `docs/evidence/ML-RESULTS.md`.

Results: `results/` (bench, parity, MQTT end-to-end on TEST).

## Limits
- The CNN scores below the deployed trees on the held-out sets (CinC 0.623 vs 0.862, VTaC 0.665 vs 0.832).
- With batch size 1, this small network is about 0.25 ms slower on the NNPA than on one CPU
  core (median 2.1 vs 1.9 ms). The accelerator does not make it faster here.
- There is one message per alarm episode. The brain re-sends its M2 score every 5 s from the same window.
