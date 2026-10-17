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
