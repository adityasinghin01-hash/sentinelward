# SentinelWard in containers (IBM LinuxONE, s390x)

The same ward runs as six containers: hub (Mosquitto 2.0.22, the newest 2.0.x with an s390x image), database (PostgreSQL 16), and four
app services from one image built on LinuxONE (`api`, `brain`, `sim`, `attacks`). It is a second,
isolated copy next to the bare-metal systemd stack: its own private network, hub and database;
only the web app is published, on `127.0.0.1:8001`.

Build the merged Vite screens with `cd web && npm ci && npm run build` first.
The API mounts `web/dist` by default; `SW_FRONTEND_DIR` can override that directory.
The service image includes the fresh `ml_v2/` model code and artifacts required by the brain.

## Run (on the build server)

    sudo apt-get install -y docker.io docker-compose-v2 && sudo usermod -aG docker linux1   # once, then log in again
    cd ~/sw/app/deploy/containers
    ./make-env.sh                          # random DB password, mode 600, never printed
    ./sync-frontend.sh                     # readable copy of web/dist for the non-root api
    docker compose build                   # builds sentinelward:latest for s390x
    docker compose up -d
    curl -s 127.0.0.1:8001/api/health
    ./evidence.sh                          # captures for the judges (criterion 3)

## Why it is built this way

- **One image, one job per container**, so each service can be restarted, limited and scaled on its own.
- **Hardened by default:** non-root user (uid 10001), read-only root filesystem, all Linux
  capabilities dropped, `no-new-privileges`, memory and CPU limits per service, secrets from files
  (Docker secrets and an env file with mode 600), no host ports except the web app on localhost.
- **Native s390x:** numpy, scipy, pandas and scikit-learn come from Ubuntu's s390x packages, the
  same as the bare-metal server; only pure-Python packages come from pip (pinned in
  `requirements-container.txt`: `deploy/requirements-server.txt` minus `wfdb`, which only the
  pack builder in `data/` uses and whose deps would need a compiler on s390x). No compiler in the image.
- **Scalability:** the simulator's scale mode measures how many beds one brain container keeps up
  with; `docker stats` shows the cost of each container. Beds-per-brain test (ward sim and attacks
  stopped so only scale beds reach the brain):

      docker compose stop sim attacks
      SW_BRAIN_MAX_BED=96 SW_BRAIN_TICK_STATS=1 docker compose up -d --no-deps --force-recreate brain
      docker compose run --rm --no-deps -T sim python -m sw_sim scale --packs /packs --runs /runs/simulator \
        --script /app/simulator/ward_script.yaml --first-bed 1 --beds 96 --seconds 180
      docker logs sentinelward-brain-1 2>&1 | grep tick_stats     # tick ms, verdicts, msgs in, drops
      docker compose up -d                                         # back to the 12-bed ward

  `--loop` restarts each pack at its end, for soak runs longer than a pack (22 min).
- **Health:** hub (a real `mosquitto_sub` of its uptime topic), api (`/api/health` must say
  `ok: true`) and db (`pg_isready`) have healthchecks; app services wait for a healthy hub. brain,
  sim and attacks serve no port, so they show plain `Up` rather than a health state.

The agents join as their own container in Phase 3 (fresh agents_v2).
