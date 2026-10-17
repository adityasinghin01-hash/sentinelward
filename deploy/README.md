# Mac → LinuxONE deployment

Run from this worktree on the Mac:

```bash
./deploy/deploy.sh --dry-run
./deploy/deploy.sh
```

The dry run is entirely offline: it prints the operations without building or contacting the server.
The real deploy builds in a temporary copy, including a temporary npm cache. It runs `npm ci` and
`npm run build` with `VITE_SENTINELWARD_RUNTIME_MODE=backend`,
`VITE_SENTINELWARD_API_BASE_URL=/api`, and no `VITE_SENTINELWARD_WS_URL` (the adapter derives
same-origin `/ws`). Neither the frontend checkout nor its lockfile is changed.

Target: `linux1@148.100.112.19`, `ssh -4`, key `~/.ssh/claudebuild.pem`. `SW_SSH_KEY` can override the
key path. Existing noninteractive sudo must permit unit installation and systemctl. The script
never transfers a key or `.env`, never prints installer/registry output or journal messages, and
never opens firewall ports. Access the site through the printed SSH port-forward command.

The repo goes to `/home/linux1/sw/app`; **ml_v2/ model artifacts are included**. Secrets, `.git`, venvs,
node_modules, local caches, generated web/dist and test outputs are excluded. Existing packs,
data, run logs and `/home/linux1/sw/.env` are preserved. No rsync delete is used. Repeating the
script reinstalls editable packages and restarts the same four units. It intentionally restarts
services, so run it between measurements. Existing server data remains outside the app checkout.

`install_deps.py` reads the five packages' current pyproject requirements and their installed/wheel
metadata. It checks existing versions and installs **only missing universal wheels**, always with
`--no-deps`; project installs also use `--no-build-isolation`. numpy/scipy/pandas are verified as
Ubuntu packages; scientific packages, PyYAML and psutil are never pip-installed. If a native package
such as pydantic-core is absent, or an installed package is incompatible, preflight stops with an
explicit provisioning message. Provision those dependencies separately in the existing server
venv; do not solve that error by pip-installing numpy/scipy/pandas. No optional ML dependencies are
installed: the brain's documented fallback remains available when an artifact runtime is absent.

All four units run as linux1, load `/home/linux1/sw/.env`, restart automatically, and log to journal.
The API binds 127.0.0.1:8000 and serves `app/web/dist`; simulator and attacks wait for demo
control. Simulator events are in `~/sw/runs/simulator/<run_id>/events.jsonl`; attack events are in
`~/sw/runs/attacks/<run_id>/events.jsonl`. `service_env.py` maps server `MQTT_*` credentials to the
brain's `SW_MQTT_*` names, without overriding explicit brain or attack-specific settings.

The backend is Phase B (PostgreSQL). `service_env.py` sets `SW_PG_DSN` from the server's
`DATABASE_URL` for sw-api when `SW_PG_DSN` is unset; without it the API would silently run in
memory mode. `/api/health` reports actual storage/durability (verified on the server:
`"storage":"postgresql","durable":true`). A1–A9 and
Kartik's authenticated network extractor are separate owners/services; these four units do not
start them. Smoke/T8 report their missing outputs honestly.

After `POST /api/demo/reset` the brain stops scoring until the next `demo_control run` (by design in
`sw_brain.service`). tests_system/smoke_h6.py starts its own simulator without a run control, so
run it on a freshly (re)started sw-brain, or after a run, not after a reset:
`sudo systemctl restart sw-brain`.

Local validation covers shell syntax, offline dry-run, the isolated frontend build, Python parsing
and synthetic metrics. SSH/rsync, sudo, systemd, native dependency compatibility and all live timing
remain server checks. There is no automatic rollback of code or dependencies. An interrupted deploy
can be rerun; restore the desired checkout and deploy it again to revert application code.
