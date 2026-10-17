# Build server setup (tessnovabuild, 148.100.112.19), done 17 Oct 2026

Recipe: build prompt 01 + doc 17. Connect with `ssh -4 -i ~/.ssh/claudebuild.pem linux1@148.100.112.19`.
Machine: IBM z17 9175/702 under z/VM 7.3.0, 3 CPU, 7.8 GiB, Ubuntu 24.04.4, Python 3.12.3, `nnpa` present (see `evidence/`).

## What is installed
- apt: mosquitto + clients 2.0.18, postgresql 16.15, python3-venv/pip, libopenblas0, libpq5, libsndfile1, git,
  python3-numpy 1.26.4, -scipy 1.11.4, -pandas 2.1.4, -sklearn 1.4.1, -yaml, -psutil, -pytest.
- venv `~/sw/.venv` (`--system-site-packages`); pip pins in `requirements-server.txt`. numpy/scipy/pandas come from
  Ubuntu, never pip. `wfdb` installed `--no-deps`: it declares pandas>=2.2.3 / scipy>=1.13, but reads both datasets fine
  with Ubuntu's older versions (checked). Recreate: `pip install -r requirements-server.txt` (keep wfdb `--no-deps`).

## Hub (Mosquitto)
- `mosquitto/sentinelward.conf` -> `/etc/mosquitto/conf.d/sentinelward.conf`. Listener `127.0.0.1:1883` only,
  persistence on (retained messages survive a restart, checked), `max_queued_messages 10000`.
- TEMPORARY: `allow_anonymous true` (localhost only). Kartik's Dynamic Security lines are in the file, commented, with the
  Ubuntu s390x path `/usr/lib/s390x-linux-gnu/mosquitto_dynamic_security.so`. He switches them on and sets anonymous false.
- Log: Ubuntu's main config already has a `log_dest file`, and Mosquitto allows only one, so
  `~/sw/deploy/logs/mosquitto.log` is a symlink to `/var/log/mosquitto/mosquitto.log` (read with sudo).

## Database
- PostgreSQL 16, `127.0.0.1:5432` only. Database `sentinelward`, owner role `sw_api`. Password generated on the server and
  stored only in `~/sw/.env` (mode 600; keys PGHOST PGPORT PGDATABASE PGUSER PGPASSWORD DATABASE_URL MQTT_HOST MQTT_PORT).
  Tables come from part 05.

## Not done (by design)
No firewall port opened (only SSH listens externally). No systemd units for backend/simulator yet (parts 04/05).
Reach the backend later via `ssh -4 -L 8000:localhost:8000`.

## Data in `~/sw/data/`
### 2015 challenge (`challenge-2015/`), from PhysioNet challenge-2015 1.0.0 `training/`, fetched on the server
v221l (VT, true alarm), a123l (asystole, false alarm), f543l (VF/flutter, true alarm): `.hea` + `.mat` (660,024 B each).
All three read with wfdb: II, V, PLETH, ABP at 250 Hz, 82,500 samples.

### MIMIC-III matched waveform sample (`mimic/`), relayed from the test server through the Mac (tar pipe, no keys on servers)
Layout mirrors the sample: `mimic/SAMPLE_SHA256SUMS.txt`, `mimic/p00/<patient>/...`. 822 data files, 952.7 MB;
all 822 pass `sha256sum -c` against `SAMPLE_SHA256SUMS.txt`.

| Patient | Copied | Files | Bytes |
|---|---|---|---|
| p000052 | whole folder | 57 | 194,612,879 |
| p000107 | whole folder | 613 | 217,766,858 |
| p000154 | whole folder | 59 | 215,415,488 |
| p000160 | whole folder | 49 | 160,598,856 |
| p000109 | one piece: master `p000109-2142-01-14-18-53`, segments `3407610_0006`..`_0020` (15, 32.11 h), `3407610_layout.hea`, numerics `p000109-2142-01-14-18-53n.hea` + `3407610n.dat` | 34 | 150,088,031 |
| p000298 | one piece: master `p000298-2148-01-02-18-16`, segments `3129212_0016`..`_0018` (3, 10.49 h), `3129212_layout.hea`, numerics `p000298-2148-01-02-18-16n.hea` + `3129212n.dat` | 10 | 14,239,436 |

Why: full p000109 (1.47 GB) and p000124 (2.7 GB) were too big to relay over mobile data (measured ~1.4 Mbit/s).
p000109: only its longest continuous piece where every segment has both II and PLETH.
p000124 replaced by the smallest candidate with a >=1 h II+PLETH piece. Candidates (folder size, longest piece):
p000298 17.8 MB 10.49 h (chosen) · p000262 140.1 MB 10.25 h · p000333 209.1 MB 29.01 h · p000222 339.5 MB 12.75 h · p000188 917.9 MB 22.43 h.

"Piece" = consecutive segments in one master header with no `~` gap and no segment missing II or PLETH, found with
`pick_segments.py` (stdlib only, read-only, run on the test server). Durations = sum of segment lengths at 125 Hz.

Loader note: the p000109/p000298 master `.hea` files list segments that were NOT copied, so `wfdb.rdrecord(master)` will
fail on them. Read the copied segments directly (`3407610_0006`..`_0020`, `3129212_0016`..`_0018`).
