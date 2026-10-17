# Containers on LinuxONE (criterion 3)

Raw: `raw/containers/` (copied from the container job's evidence) and `raw/resources-now.txt` (captured 2026-10-17 14:27 UTC).

- One s390x image (`sentinelward:latest`, built on LinuxONE from `deploy/containers/Dockerfile`), one job per container: api, brain, sim, attacks, plus hub (eclipse-mosquitto 2.0.22, the 2.0.18 tag has no s390x image) and db (PostgreSQL 16). Isolated network; only the web app is published, on 127.0.0.1:8001.
- Hardened: non-root user (uid 10001), read-only root filesystem, all Linux capabilities dropped, `no-new-privileges`, per-service CPU and memory limits, secrets from files (mode 600). No compiler in the final image (`raw/containers/no-compiler.txt`): numpy/scipy/pandas/scikit-learn come from Ubuntu's s390x packages, `wfdb` (pack builder only) is not installed.
- Healthchecks: hub (mosquitto_sub) and api (`/api/health` ok) report `healthy`; db healthy.
- Two full 20-minute 12-bed ward runs inside the containers: 11,790 messages each, 0 invalid; send lag p99 24.7 ms and 40.3 ms.
- A real bug found and fixed by measuring: the attacks container was OOM-killed at its 128 MiB limit 13 minutes into run 1 (`raw/containers/oom-attacks-128m.txt`); limits were set from measured peaks and per-bed history was bounded, after which memory stays flat (`raw/memory-flat.txt`, `SCALE.md`).
- Beds per brain container: `SCALE.md` (12, 24, 48, 96 beds; 96 beds use 22% of the 5 s tick on 1 CPU).
