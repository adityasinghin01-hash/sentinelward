# Bed packs (built 17 Oct 2026)

Packs live on the build server in `~/sw/packs` (12 × `.npz` + `.json` + `summary.md`, 17.5 MB).
B01–B07, B11, B12 built on LinuxONE from `~/sw/data`; B08–B10 built on the Mac from our PhysioNet VitalDB 1.0.0
`.vital` files (sha256 match `SHA256SUMS.txt`), then copied (sha256 identical) and verified on the server.

| Bed | Source | Window | s | Size | Verify Mac / server |
|---|---|---|---|---|---|
| B01 | MIMIC p000109 `3407610_0006` (see note 1) | piece +7200 s | 1320 | 2.00 MB | – / PASS |
| B02 | MIMIC p000052 `3533390_0011` | piece +0 s | 1320 | 2.00 MB | – / PASS |
| B03 | 2015 v221l, VTACH true | whole record | 330 | 0.50 MB | – / PASS |
| B04 | 2015 a123l, ASYSTOLE false (H1 confirmed) | whole record | 330 | 0.50 MB | – / PASS |
| B05 | MIMIC p000107 `3860035_0044` (note 2) | piece +0 s | 1320 | 1.34 MB | – / PASS |
| B06 | MIMIC p000154 `3783784_0006` (pick-mimic #1) | piece +0 s | 1320 | 1.34 MB | – / PASS |
| B07 | 2015 f543l, VFIB true (H1 confirmed) | whole record | 330 | 0.50 MB | – / PASS |
| B08 | VitalDB 5552 | file min 231–253 | 1320 | 2.00 MB | PASS / PASS |
| B09 | VitalDB 912 | file min 38–60 | 1320 | 2.00 MB | PASS / PASS |
| B10 | VitalDB 4277 (H1 confirmed, backup 5659 not needed) | file min 12–34 (note 3) | 1320 | 2.00 MB | PASS / PASS |
| B11 | MIMIC p000160 `3531764_0003` (pick-mimic #2) | piece +0 s | 1320 | 2.00 MB | – / PASS |
| B12 | MIMIC p000298 `3129212_0016` (pick-mimic #3) | piece +0 s | 1320 | 1.34 MB | – / PASS |

Notes
1. Doc 12 names p000109 piece `3346682_0014`; only p000109's `3407610_0006..0020` was copied to the server
   (deploy/SETUP.md). B01 uses the same patient, same signals (II, V, AVR, PLETH, RESP), 2 h in. Not a doc-named backup.
2. p000107's numerics header is `...-21-02n` while its master is `...-21-01`; the loader now finds it by its
   `3860035n.dat` file and applies the +11 s start difference. B05 and B12 numerics are 1 per minute, so hr/spo2/rr
   step once a minute.
3. `check 4277.vital` first suggested minute 0, but ART reads about −12 mmHg (line not connected) in minutes 0–9.
   `check` now rejects windows with any ART minute >5 % under 20 mmHg and suggests minute 12. Cuff readings in this
   window are at 43, 107, 175, 247, 315 s only (none during the T+06:00–13:00 hacker drift). Last window minute has high ART (median 122, likely a flush).
4. B08: ART reads about −14 mmHg in its last 2 min (file min 251–253), outside doc 12's 20-minute run.
   B09: cuff MAP 64 at 363 s and 57 at 513 s (doc 12's T+06:06 / T+08:36); HR reads 0 for 82 s (real glitch).
5. B11 SpO2 is 60.8 % missing (not required). Server pytest: 51 pass, 6 VitalDB tests fail by design (big-endian guard).

## v1.3 packs with a second ECG lead (built 17 Oct 2026): `~/sw/packs-v13`

Same beds, windows and commands as above, loader 1.3.0 (doc 00 v1.3 adds the optional `ecg2`). B01–B07, B11, B12 built
on LinuxONE; B08–B10 on the Mac and copied (sha256 identical). `verify` 12/12 PASS on the server. Every array that was
already in `~/sw/packs` has the same sha256 in `~/sw/packs-v13`; the only new array is `ecg2`. `~/sw/packs` is unchanged.
The 2015 and MIMIC beds get lead V as `ecg2`; our three VitalDB files have only `SNUADC/ECG_II`, so B08–B10 have no `ecg2`.

| bed | device | source | window | duration_s | channels | missing % | cuff | alarms | status |
|---|---|---|---|---|---|---|---|---|---|
| B01 | MON-01 | MIMIC p000109/3407610_0006 | piece +7200 s | 1320 | ecg ecg2 ppg resp hr spo2 rr | ecg 0.0 ecg2 0.0 ppg 0.0 resp 0.0 hr 0.0 spo2 0.0 rr 0.0 | 1 | - | OK |
| B02 | MON-02 | MIMIC p000052/3533390_0011 | piece +0 s | 1320 | ecg ecg2 ppg resp hr spo2 rr | ecg 0.1 ecg2 0.0 ppg 0.0 resp 0.0 hr 0.0 spo2 0.0 rr 0.7 | 2 | - | OK |
| B03 | MON-03 | 2015 v221l | whole record | 330 | ecg ecg2 ppg abp hr spo2 rr | ecg 0.0 ecg2 0.0 ppg 0.0 abp 0.0 hr 0.0 spo2 100.0 rr 100.0 | 0 | VTACH@300s T | OK |
| B04 | MON-04 | 2015 a123l | whole record | 330 | ecg ecg2 ppg abp hr spo2 rr | ecg 0.0 ecg2 0.0 ppg 0.0 abp 0.0 hr 0.0 spo2 100.0 rr 100.0 | 0 | ASYSTOLE@300s F | OK |
| B05 | MON-05 | MIMIC p000107/3860035_0044 | piece +0 s | 1320 | ecg ecg2 ppg hr spo2 rr | ecg 0.0 ecg2 0.0 ppg 1.1 hr 0.0 spo2 0.4 rr 0.0 | 2 | - | OK |
| B06 | MON-06 | MIMIC p000154/3783784_0006 | piece +0 s | 1320 | ecg ecg2 ppg hr spo2 rr | ecg 0.0 ecg2 0.0 ppg 0.0 hr 0.0 spo2 1.1 rr 0.0 | 1 | - | OK |
| B07 | MON-07 | 2015 f543l | whole record | 330 | ecg ecg2 ppg abp hr spo2 rr | ecg 0.0 ecg2 0.0 ppg 0.0 abp 0.0 hr 0.3 spo2 100.0 rr 100.0 | 0 | VFIB@300s T | OK |
| B08 | MON-08 | VitalDB 5552 | minute 231.0 | 1320 | ecg ppg abp hr spo2 rr | ecg 0.0 ppg 0.0 abp 0.0 hr 1.9 spo2 1.9 rr 1.9 | 6 | - | OK |
| B09 | MON-09 | VitalDB 912 | minute 38.0 | 1320 | ecg ppg abp hr spo2 rr | ecg 0.0 ppg 0.0 abp 0.0 hr 1.1 spo2 1.8 rr 0.0 | 7 | - | OK |
| B10 | MON-10 | VitalDB 4277 | minute 12.0 | 1320 | ecg ppg abp hr spo2 rr | ecg 0.0 ppg 0.0 abp 0.0 hr 0.0 spo2 0.0 rr 10.2 | 5 | - | OK |
| B11 | MON-11 | MIMIC p000160/3531764_0003 | piece +0 s | 1320 | ecg ecg2 ppg abp hr spo2 rr | ecg 0.0 ecg2 0.0 ppg 0.0 abp 0.3 hr 0.0 spo2 60.8 rr 0.3 | 2 | - | OK |
| B12 | MON-12 | MIMIC p000298/3129212_0016 | piece +0 s | 1320 | ecg ecg2 ppg hr spo2 rr | ecg 2.1 ecg2 3.5 ppg 0.6 hr 0.0 spo2 0.0 rr 0.0 | 0 | - | OK |
