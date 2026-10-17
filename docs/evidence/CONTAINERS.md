# Containers on LinuxONE (criterion 3)

The six-container copy and the secured agents-on systemd ward are separate deployments.
The service-account authentication change below is configured in source; its LinuxONE
acceptance results were captured on LinuxONE on 18 Oct 2026 (03:20 IST) in `raw/containers-auth/`.
Older captures in `raw/containers/` predate it.

## What the existing container evidence establishes

Raw: `raw/containers/` and `raw/resources-now.txt` (2026-10-17 14:27 UTC).

- Native s390x packaging: one app image, separate `api`, `brain`, `sim`, `attacks` jobs,
  plus Mosquitto hub and PostgreSQL db. Only the API is published, on `127.0.0.1:8001`.
  See `raw/containers/image.txt`, `compose-ps.txt` and `health.json`.
- **The four app containers** run as non-root uid 10001 with read-only root filesystems,
  all capabilities dropped, `no-new-privileges`, and CPU/memory limits (`hardening.txt`).
  These properties do not apply wholesale to hub/db. Hub/db have memory limits and
  `no-new-privileges`; hub startup and CLI probes use root, while the broker drops to mosquitto.
- No compiler in the app image (`no-compiler.txt`); scientific Python uses Ubuntu's s390x
  packages. `wfdb`, needed for building packs only, is excluded.
- Historical run report: two 20-minute 12-bed container replays, 11,790 messages each,
  0 invalid, send lag p99 24.7 ms and 40.3 ms. These were not authenticated-stack reruns.
  The saved `compose-ps.txt` shows only db healthy; the later `raw/resources-now.txt`
  captures hub/API/db healthy. New hub health uses an authenticated subscription ACK.
- `oom-attacks-128m.txt` records the earlier attacks OOM; limits were raised. The later
  bounded-history soak is described in `SCALE.md` and `raw/memory-flat.txt`.
- `SCALE.md` reports 12/24/48/96 beds per brain container, with three-minute runs and a
  maximum 96-bed tick of 1.12 s on one CPU. These measurements predate this auth change,
  do not include agents/witness, and are not a long 96-bed soak. Its referenced raw tick
  logs must be supplied separately; `raw/containers/scale-stats.txt` is an older run that
  rejected extra beds and cannot substitute for those logs.

## Configured container security and its limits

The hub now sets `allow_anonymous false`, uses a generated Mosquitto-format password file,
and defaults topic ACLs to deny. `make-env.sh` generates independent simulator, brain, backend
and attacks accounts plus service env/CLI files (0600; private directories 0700), without
printing passwords or rotating them on repeat runs. They are Git-ignored and excluded from
the Docker build context. The hash file is copied from the secret mount into tmpfs before
Mosquitto drops privileges. The `ward` network is internal; 1883 is never host-published.

Brain/backend/attacks ACLs mirror `security_v2/sw_sec/policy.py`. The simulator's direct
entrypoint uses one connection for all beds, so its role deliberately permits
`ward/bed/+/vitals`, including scale beds. It does **not** establish per-monitor identity,
client-ID binding, own-bed isolation or per-device containment. Attacks deliberately writes
B01–B12 vitals. Only brain writes scores/verdicts; no service can write network features or
dynsec commands. MQTT between containers is plaintext; host/Docker administrators remain trusted.
See `deploy/containers/README.md` for the role table, credential readers and rotation limits.

No agents or network-witness container was added. They are OFF/absent, including Telegram.
A safe addition needs packages, persistent agent state, reviewed env/secrets and dynsec
containment; the extractor also needs broker PUBLISH/connection logs with readable, retained
storage mounted read-only into it. The single simulator identity cannot supply the systemd
per-monitor sender evidence. This is beyond a small packaging change.

Only the separate systemd evidence establishes agents, network witness operation, per-monitor
dynsec ACLs/cut-off/Undo, TLS 8883 and the recorded **15/15 live security test**
(`SECURITY.md`, `security_v2/SECURITY.md`, `raw/security-live-20261017T140649Z.json`).
Those results must not be attributed to Compose, nor combined with container scale into one run.

## Deploy and capture service-account authentication

Run on the isolated container copy, between demos, after syncing this branch. Build the web
screens and ward packs as documented in `deploy/containers/README.md`; packs are not in Git.
The commands below preserve generated credentials and existing volumes. Force recreation is
needed so the hub takes the new startup/config mounts and apps load their service credentials.

```bash
cd ~/sw/app
(cd web && npm ci && npm run build)
cd deploy/containers
./make-env.sh
./sync-frontend.sh
docker compose config --quiet
docker compose build
docker compose up -d --force-recreate --wait --wait-timeout 120
mkdir -p evidence-out
(
  set -euo pipefail
  trap 'docker compose up -d --wait --wait-timeout 120 api brain sim attacks' EXIT
  docker compose stop api brain sim attacks
  ./verify-auth.sh | tee evidence-out/auth.txt
)
curl --fail --silent --show-error 127.0.0.1:8001/api/health
SW_EVIDENCE_OUT=./evidence-out ./evidence.sh
```

`verify-auth.sh` invokes `mosquitto_sub`/`mosquitto_pub` **inside this Compose hub** using
root-only CLI configs, never password arguments. It checks anonymous CONNACK 135, each
account's authenticated subscription, positive QoS 1 publish ACKs and negative PUBACK 135
for an independent fixed topic matrix (all write classes, twelve attack beds, B13/B96,
features, dynsec and other forbidden/extra-level topics). It requires broker reason codes;
timeouts/connection errors/missing ACKs fail. A zero CLI exit alone does not prove a publish
was authorized. The matrix is representative, not an exhaustive topic-space/read-isolation proof.
Probes are non-retained schema-invalid JSON; stop apps to avoid polluting run metrics.

Do not capture resolved `docker compose config` or full container environments: they contain
secrets. Collect `evidence-out/auth.txt`, `compose-ps.txt`, `hardening.txt`, `health.json`,
`platform.txt`, `image.txt` and `stats.txt` from this deploy; review before copying to evidence.
Do not overwrite old captures or label them as this run.

- Local checks: shell syntax; setup twice in a temporary directory (16 files unchanged,
  0600/0700 permissions); password format cross-check with installed `mosquitto_passwd`.
  Docker CLI is absent; Compose YAML is validated with Python instead. A local broker could
  not listen under the sandbox, so no local MQTT authentication result is claimed.
- Authenticated LinuxONE build/start/health: PASS. All six containers healthy/up after
  `--force-recreate`; API `ok`, MQTT and database connected (`raw/containers-auth/compose-ps.txt`,
  `health.json`, `hardening.txt`, `image.txt`, `platform.txt`, `stats.txt`). First deploy found a real bug:
  the internal-only network stopped Docker publishing the API port; the API now also joins an `edge`
  network, the `ward` network stays internal.
- Anonymous refusal and service-account ACL matrix: PASS, 137 checks, 0 failed; anonymous connect
  refused with CONNACK 135 (`raw/containers-auth/auth.txt`).
- Authenticated container replay: 40-second spot check only. Ward script started at 9:00; 10 beds online,
  0 invalid messages, verdicts on all reporting beds incl. B10 TAMPERING, no auth errors in the logs
  (`raw/containers-auth/replay-check.txt`). No full 20-minute or scale rerun on the authenticated stack.
