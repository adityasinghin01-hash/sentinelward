# SentinelWard in containers (IBM LinuxONE, s390x)

The same ward runs as six containers: hub (Mosquitto 2.0.22), database (PostgreSQL 16), and four
app services from one image built on LinuxONE (`api`, `brain`, `sim`, `attacks`). It is a second,
isolated copy next to the bare-metal systemd stack: its own private network, hub and database;
only the web app is published, on `127.0.0.1:8001`.

Build the merged Vite screens with `cd web && npm ci && npm run build` first.
The API mounts the readable `web-dist` copy made by `sync-frontend.sh`; `SW_FRONTEND_DIR` can override it.
The service image includes the fresh `ml_v2/` model code and artifacts required by the brain.

## Run (on the build server)

    sudo apt-get install -y docker.io docker-compose-v2 && sudo usermod -aG docker linux1   # once, then log in again
    cd ~/sw/app/deploy/containers
    ./make-env.sh                          # DB + four MQTT accounts; preserves secrets, files 0600
    ./sync-frontend.sh                     # readable copy of web/dist for the non-root api
    docker compose config --quiet          # validates without printing resolved secrets
    docker compose build                   # builds sentinelward:latest for s390x
    docker compose up -d --force-recreate --wait --wait-timeout 120
    curl -s 127.0.0.1:8001/api/health
    # Run the isolated auth-probe subshell below before capturing evidence.
    SW_EVIDENCE_OUT=./evidence-out ./evidence.sh

## Why it is built this way

- **One image, one job per container**, so each service can be restarted, limited and scaled on its own.
- **App hardening (`api`, `brain`, `sim`, `attacks`):** non-root user (uid 10001), read-only
  root filesystem, all Linux capabilities dropped, `no-new-privileges`, and CPU/memory limits.
  Hub and db have memory limits and `no-new-privileges`; they do not inherit the app hardening.
  The hub starts as root to copy/chown its password file into tmpfs, then Mosquitto drops to its
  own user. Root health/auth probes read private CLI configs. No host ports except the localhost API.
- **Private network:** `ward` is internal, with no published 1883 or 5432. Internal MQTT is
  plaintext with password-file authentication and static topic ACLs; this is not TLS or dynsec.
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
- **Health:** hub (authenticated `mosquitto_sub -E` acknowledgement on demo control), api (`/api/health` must say
  `ok: true`) and db (`pg_isready`) have healthchecks; app services wait for a healthy hub. brain,
  sim and attacks serve no port, so they show plain `Up` rather than a health state.

## MQTT setup and role boundaries

`make-env.sh` needs Python 3 only, not a running broker. It generates four independent random
MQTT passwords and salted PBKDF2-HMAC-SHA512 hashes in Mosquitto's `$7$` password-file format.
All generated files are 0600, `.mqtt/` directories are 0700, and repeat runs preserve credentials
and unchanged files. Keep `.mqtt/credentials.json`, `.mqtt/passwords`, per-service env files,
client configs, `db_password.txt` and `.env.containers` private. Git ignores them; the
Dockerfile-specific ignore file also excludes them from the build context. Do not capture
`docker compose config` without `--quiet`, `docker inspect` environments, or env-file contents.
Docker administrators can still read runtime environment secrets.

The script refuses symlinks and inconsistent existing credentials instead of silently rotating
them. If it reports partial state or a stale `.tmp`, inspect/recover private files before retrying.
Do not delete `db_password.txt` for an existing database: PostgreSQL's initialized volume retains
its old password. Rotation needs a planned DB/broker change and app recreation. The hub copies
its hash file at startup; recreate the hub and apps after an intentional MQTT rotation.

| Compose service / username | Publish | Read |
|---|---|---|
| sim / simulator | `ward/bed/+/vitals` | demo control |
| brain / brain | bed scores and verdicts | vitals, network features, bedside, demo control |
| api / backend | request, demo control, action, bedside | contract topics plus chip scores |
| attacks / attacks | vitals for B01–B12 only | vitals, demo control |

Unlisted topic access defaults to deny. Brain, backend and attacks mirror
`security_v2/sw_sec/policy.py`. The deliberate exception is the simulator: its unmodified
entrypoint multiplexes beds on one connection, so it has a wildcard vitals grant that also
allows the documented 96-bed scale command. It has no per-monitor identities, client-ID binding,
cross-bed isolation or per-device cut-off. The attacks account is deliberate demo authority;
a compromised simulator can forge every bed, and attacks can forge B01–B12. No account can
publish network features, and only brain can publish scores/verdicts. The generated env files
provide `MQTT_USER`/`MQTT_PASS` for sim/API, `SW_MQTT_USERNAME`/`SW_MQTT_PASSWORD` for brain,
and `SW_ATTACK_MQTT_USERNAME`/`SW_ATTACK_MQTT_PASSWORD` for attacks, matching their current readers.

## Isolated auth probes and evidence

`verify-auth.sh` runs `mosquitto_pub`/`mosquitto_sub` inside **this Compose hub**. It requires
an explicit anonymous MQTT v5 CONNACK 135, authenticated subscriptions for each account, and
QoS 1 PUBACK success/rejection codes for a fixed publish matrix. Timeouts, missing ACKs and
connection errors fail. Mosquitto 2.0.22 can exit zero for a denied publish, so exit status alone
is not accepted. The matrix covers every write class, all twelve attack beds, B13/B96 and
representative forbidden topics including features, dynsec, chip, and extra topic levels.
It is a representative authorization test, not an exhaustive topic-space or read-isolation test.

Probes are non-retained, schema-invalid JSON; they never clear retained verdicts. Run between
demos with app services stopped so rejected application messages cannot affect run metrics.
This subshell always attempts to restore the four apps, even if verification fails:

```bash
cd ~/sw/app/deploy/containers
mkdir -p evidence-out
(
  set -euo pipefail
  trap 'docker compose up -d --wait --wait-timeout 120 api brain sim attacks' EXIT
  docker compose stop api brain sim attacks
  ./verify-auth.sh | tee evidence-out/auth.txt
)
SW_EVIDENCE_OUT=./evidence-out ./evidence.sh
```

Deployment acceptance (18 Oct 2026, LinuxONE): 137/137 auth checks pass, anonymous connect refused;
see `docs/evidence/CONTAINERS.md` and `docs/evidence/raw/containers-auth/`.

## What is outside this stack

There are no optional agents or witness services in this change. `agents_v2` and Telegram
integration are OFF/absent. Adding the extractor needs broker PUBLISH/connection logging,
log retention/permissions and a read-only log-volume mount. Its sender counts would also need
per-monitor publisher identities. Agents need persistent state, reviewed agent/Telegram env,
and dynsec admin/device credentials plus the containment launcher for real cut-off/Undo.
The current app image installs neither `security_v2` nor `agents_v2`; the static hub cannot
perform dynsec containment. This is beyond a small safe addition.

The separate systemd deployment supplies agents, the network witness, per-monitor dynsec ACLs,
TLS on 8883 and the recorded 15/15 security test. Its results do not prove those capabilities
inside containers. Container evidence covers packaging, app hardening, resource limits and scale;
after deployment, the new auth capture can additionally establish this static service-account policy.
