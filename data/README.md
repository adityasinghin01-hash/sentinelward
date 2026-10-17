# sw_data: SentinelWard bed packs

`sw_data` prepares the recordings that the SentinelWard ward simulator replays as 12 live beds.
Each bed becomes one **bed pack**: already cleaned, resampled to 125 Hz and saved as explicit
little-endian float32, so the simulator only has to play it.

> **VitalDB on Mac or Colab only.** The `vitaldb` 1.7.2 package reads `.vital` files wrongly on
> big-endian machines (blood pressure came out as 32,772 mmHg on LinuxONE). `sw_data` refuses to
> read a `.vital` file when `sys.byteorder` is not `"little"`. Build B08 to B10 on the Mac or in
> Colab, and the 2015 and MIMIC beds on either machine. The packs themselves load correctly everywhere.

## Install

Allowed packages only: Python standard library, numpy, scipy, pyyaml, wfdb, and vitaldb on the Mac.

```bash
# LinuxONE (Ubuntu 24.04): numpy/scipy/pyyaml from apt, wfdb 4.3.1 already installed with --no-deps
cd data && python3 -m sw_data --help            # runs straight from the folder, no install needed
# Mac
pip install -e ".[vital,test]"
```

## Commands

```bash
python -m sw_data check <paths...> [--start-min M] [--minutes 22] [--clinical clinical_data.csv]
python -m sw_data pick-mimic <sample_root> --exclude p000052,p000107,p000109 --need 3
python -m sw_data build beds.yaml --out packs [--beds B01,B02,...]
python -m sw_data verify packs
```

* **check** prints a one-screen report per path. Paths can be a 2015 record (`.../a123l` or
  `a123l.hea`), a MIMIC piece (`.../p000052/3533390_0011`), a MIMIC master record or patient
  folder, or a `.vital` file. Every report lists the signals, original rate, length, and % missing
  and % flat (flat = at least 2 s with no change) per signal. Then by dataset:
  * 2015: alarm code, true/false label, priority.
  * MIMIC: the piece's offset in its master record, the numerics coverage, and a
    `numerics line up: YES/NO` verdict.
  * VitalDB: tracks found, cuff readings in the window, the median line-minus-cuff systolic gap
    in the window, the `aline1` status (with `--clinical`), and a **suggested start** for a
    22-minute window where every signal is valid. This is how B10's `start_min` is picked.
  At H1, run it on `a123l`, `f543l` and `4277.vital` (else `5659.vital`).
  A blank ECG unit shows as a `WARNING` line.
* **pick-mimic** goes through patient folders in sorted order, skipping the excluded patients. It
  lists the next patients that have a piece at least 1 h long with II and PLETH, plus a numerics
  record. For each it prints the piece name, the piece length and a suggested start offset: the
  first 22-minute window with II and PLETH each under 5 % missing and under 5 % flat, and numeric
  HR at most 50 % missing. Each patient appears at most once. If fewer than `--need` qualify, it
  says so, suggests VitalDB cases instead, and exits with code 1.
* **build** writes `<bed>.npz` and `<bed>.json` per bed, plus `summary.md` (one table row per
  bed). A bed that fails prints `FAIL <bed>: <reason>` and writes nothing; the other beds still
  build and the exit code is 1. `--beds` builds a subset, so the LinuxONE run and the Mac run can
  share one output folder; `summary.md` keeps the rows of beds not rebuilt.
* **verify** reloads every pack and prints one `PASS`/`FAIL` line per bed. It re-checks the sha256
  of every array, the shapes, `fs = 125`, the byte-order labels (`"little"`, every array `<f4`) and
  the missing fractions.

## beds.yaml

Holds the 12 beds of doc 12 and the paths to the source data (relative to the YAML file).
`signals` lists the **required** signals of a bed: `ecg`, `ppg`, `abp`, `resp`, `numerics`
(MIMIC), `numbers` and `cuff` (VitalDB). The fields to decide at H1 carry comments:

* `H1 PICK`: `patient`, `piece`, `start_s` of B06, B11 and B12, from `pick-mimic`.
* `H1 WINDOW`: `start_min` of B10, from `check <case>.vital`.
* `H1 CONFIRM`: B04 `a123l`, B07 `f543l`, B10 `4277` (backup `5659`).

A bed whose H1 field is still `null` fails with a clear message. A patient, record or case used
on two beds is rejected when the file is loaded. **Quote MIMIC piece names** (`piece: "3346682_0014"`):
YAML reads an unquoted `3346682_0014` as the number 33466820014, so `sw_data` rejects it.

## Bed pack format

`<bed_id>.npz`: every array is float32 with explicit little-endian dtype `'<f4'`.

| array | rate | shape | content |
|---|---|---|---|
| `ecg` | 125 Hz | `duration_s × 125` | lead II, otherwise the first ECG lead, in mV |
| `ecg2` | 125 Hz | `duration_s × 125` | v1.3, optional: a second ECG lead, in mV: lead `V` if present, else the next ECG lead in channel order (`sw_data.dsp.pick_ecg2`; VitalDB: the other SNUADC ECG track). Left out when the source has one lead or the second lead is empty in the window |
| `ppg` | 125 Hz | `duration_s × 125` | PLETH, units as stored |
| `abp` | 125 Hz | `duration_s × 125` | ABP / ART, mmHg |
| `resp` | 125 Hz | `duration_s × 125` | RESP waveform, only for beds that ask for `resp` |
| `hr` | 1 Hz | `duration_s` | beats/min |
| `spo2` | 1 Hz | `duration_s` | % |
| `rr` | 1 Hz | `duration_s` | breaths/min |
| `nibp` | per reading | `(n, 4)` | `[t_offset_s, sys, dia, map]` per NEW cuff reading; `(0, 4)` if none |

A waveform is left out when the source has none. `hr`, `spo2`, `rr` and `nibp` are always present
(all-NaN or empty when there is no source). **Missing is NaN** (sent as `null` on the wire), never 0;
0 is a real flatline.

`<bed_id>.json` holds:

* `bed_id`, `device_id` (B01 → MON-01 … B12 → MON-12);
* `source`: dataset, record or case, patient and piece, master record, the window start in the
  original recording (`window_start_s`; for MIMIC also `master_offset_s`), the channel used for each
  pack array (`channels`: name, original rate, units), and every original channel
  (`original_channels`);
* `fs` (125), `duration_s`, `channels` (the arrays present), `byte_order` (`"little"`),
  `dtype` (`"<f4"`), `shapes`;
* `alarms`: list of `{t_offset_s, code, true_alarm, priority}` (2015 only; MIMIC and VitalDB carry none);
* `missing_pct` per channel, `nibp_readings`, `notes`;
* `sha256` of each array (its `<f4` bytes), `loader_version`, `created_utc`.

## Processing

* **Resampling.** `scipy.signal.resample_poly` to 125 Hz (250 → 125 is down 2, 500 → 125 is down 4,
  125 passes through). Missing stretches are filled linearly only to run the filter. Then output
  sample *k* (at input position *k·d*) goes back to NaN if any input in `[k·d−(d−1), k·d+(d−1)]`
  was missing. A gap therefore grows by at most one output sample on each side.
  One second of real signal on each side of the window (where available) feeds the filter and is
  cropped off afterwards.
* **Second ECG lead (v1.3).** Same cleaning, unit conversion and resampling as `ecg`. It is never
  required, so it never fails a bed; `source.channels.ecg2` names it. The same rule
  (`pick_ecg2`) builds the training table of the 2-lead M2 model (`ml_v2/m2gbt/prep.py`).
* **Missing values.** wfdb's missing marker is already NaN; the constant −32768 is turned into
  NaN in every channel.
* **Units** come from wfdb/vitaldb physical values, never from rescaled raw integers. ECG in `uV`
  is divided by 1000 to mV (noted in the json). A blank ECG unit is kept as is, noted, and warned
  about in `check`.
* **Heart rate.** MIMIC: numerics `HR`. VitalDB: `Solar8000/HR`, held onto a 1 s grid for under
  2 s, so a missed 2 s sample shows as NaN. 2015: from the 125 Hz ECG. The ECG is band-passed
  5–15 Hz (2nd-order Butterworth, zero phase), and peaks of |x| are found 0.25 s apart or more,
  above max(0.35 × 98th percentile of the 8 s block, 0.15 × the record's 98th percentile,
  0.1 mV). `hr[t]` = round(60 / median beat gap) over the 5 s ending at the end of second *t*.
  Fewer than 2 beats in a full 5 s window with the ECG at least 50 % valid gives 0. A window more
  than 50 % missing, or a missing ECG, gives NaN. During the first 5 s it is never 0 (NaN instead).
* **SpO2 / breathing rate** come from MIMIC numerics (`SpO2`, `RESP`) or VitalDB
  (`Solar8000/PLETH_SPO2`, `Solar8000/RR_CO2` else `Solar8000/RR`); otherwise NaN. 2015 has neither.
* **Cuff.** A new reading means the systolic value changes and is not NaN (compared with the
  previous non-NaN value, including values from before the window). All three values and the time
  are stored.
* **MIMIC alignment.** A piece's offset in its master record is the sum of the earlier segment
  lengths (including `~` gaps) divided by 125. The numerics record starts with its master record.
  If both headers carry a start date and time and these differ, the difference is applied and noted.
* **2015 alarms.** One alarm at `t_offset_s = 300` with the code, label and priority from the header.
* **VitalDB.** Only our `.vital` files, read whole with `vitaldb.VitalFile(path)`; never
  `vitaldb.load_case`. `start_min` counts from the start of the file (`window_ref: file`); with
  `window_ref: opstart` it counts from `opstart` in `clinical_data.csv`. A case needs a non-empty
  `aline1` in `clinical_data.csv` before its ART signal is used.
* **Failing loudly.** A missing source, a window that does not fit, or a required signal that is
  absent or more than 50 % missing stops that bed with `<bed>: <reason>`. Packs are computed in
  memory, written to temporary files and renamed, so no half-made pack is ever left.

## Known limits

* **Two identical cuff readings in a row count as one** (a new reading is detected as a change in
  systolic value).
* 2015 HR is limited to 240 beats/min by the 0.25 s refractory period; during VF the beat
  detector gives a nominal rate, not a clinical one. One beat in a 5 s window counts as no beats (HR 0).
* Line-minus-cuff gap in `check`: line systolic = median of the per-second ART maxima over the
  30 s before each cuff reading.
* VitalDB `check` reports the SentinelWard tracks it looks for (found or missing), not every track in the file.
* `check` and `pick-mimic` compute flat % per 60-minute chunk, so a flat run that crosses a
  chunk boundary can be under-counted in their suggestions; the packs themselves are unaffected.
* If a bed fails, an older pack for that bed already in the output folder is left in place
  (`build` warns); `summary.md` marks the bed as FAIL.

## Tests

```bash
cd data && python -m pytest
```

The tests are offline. They write small synthetic WFDB records with `wfdb.wrsamp` into a temp
folder and use a fake object in place of `vitaldb.VitalFile`.
