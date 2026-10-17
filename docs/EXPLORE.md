# Explore SentinelWard yourself

The [README exploration section](../README.md#explore-everything-yourself) maps all saved screenshots, evidence and code. The [5-minute check](../README.md#check-it-yourself-in-5-minutes) runs without recordings, a hub or a database. Below is the longer path to a running ward. These are repository instructions and saved measurements, not a newly verified installation.

## Build the packs and start Compose

### Get the recordings

Download the sources below under their providers' terms. Point `paths:` in [data/beds.yaml](../data/beds.yaml) at your copies; paths are relative to that YAML file. Raw recordings and bed packs are not checked in. Use the current YAML and [built-pack notes](../data/PACKS.md) for actual records and windows: [spec 12](spec/12-ward-script.md) is the original plan and has older selections and expected verdicts.

| Public dataset | What to get / use | Download size recorded in the repo |
|---|---|---|
| [PhysioNet/CinC 2015](https://physionet.org/content/challenge-2015/1.0.0/) | Training records v221l, a123l and f543l, headers and waveforms, for B03/B04/B07; all training records for M2 retraining | Full download: size not measured; [SETUP](../deploy/SETUP.md) records each selected `.mat` as 660,024 B |
| [VTaC](https://physionet.org/content/vtac/1.0/) | Labelled alarm archive for M2 training/testing, not ward bed packs; [extractor](../ml_v2/data/extract_vtac.py) streams selected pre-alarm data from the zip | size not measured |
| [MIMIC-III Waveform Matched Subset](https://physionet.org/content/mimic3wdb-matched/1.0/) | Sample waveforms, headers and numerics for the six MIMIC beds in `beds.yaml` | Our copied sample: 822 data files, 952.7 MB ([SETUP](../deploy/SETUP.md)); not the size of the full database |
| [VitalDB](https://vitaldb.net/) | Cases 5552, 912, 4277 as `.vital`, plus `clinical_data.csv`, for B08/B09/B10 | size not measured |

[SETUP](../deploy/SETUP.md) gives the copied MIMIC folder/segment list and checksum check. The p000109/p000298 master headers name segments that were not copied, so use the selected pieces in `beds.yaml` rather than loading those whole masters. [PACKS.md](../data/PACKS.md) records 17.5 MB for the original built pack set; that is processed output, not a source-download estimate or a v1.3 size measurement.

### Build and verify

Use the Python environment from the README check. On a little-endian Mac, from the repository root, the [data guide](../data/README.md) supplies:

```bash
cd data
pip install -e ".[vital,test]"
python -m sw_data build beds.yaml --out packs
python -m sw_data verify packs
cd ..
```

`sw_data` reads the selected windows, preserves missing values, resamples waveforms to 125 Hz, and writes each bed's `.npz` arrays and `.json` metadata/checksums plus `summary.md`. Verify checks array hashes, shapes, sample rate and byte order. Inspect failures before starting the simulator; a failed rebuild can leave an older pack in place.

**VitalDB must be converted on a little-endian machine.** `vitaldb` 1.7.2 misreads `.vital` on big-endian LinuxONE; the builder refuses it there. Build B08–B10 on Mac/Colab, copy those generated packs to LinuxONE, and verify there. The resulting explicit little-endian float32 packs work on either architecture. On LinuxONE the other beds can be built with the existing Ubuntu scientific packages and `wfdb --no-deps`; [data/beds.yaml](../data/beds.yaml) documents the split commands:

```bash
# From data/, on LinuxONE
python -m sw_data build beds.yaml --out packs --beds B01,B02,B03,B04,B05,B06,B07,B11,B12
# From data/, on the little-endian machine
python -m sw_data build beds.yaml --out packs --beds B08,B09,B10
```

Combine all twelve beds' pack files in the mounted pack directory. The deployed systemd simulator uses `/home/linux1/sw/packs-v13` ([unit](../deploy/systemd/sw-sim.service)); Compose defaults to `/home/linux1/sw/packs`, overridden by `SW_PACKS_DIR` ([compose.yaml](../deploy/containers/compose.yaml)). Use the v1.3 builder for the optional second ECG lead; do not infer a new download size from the old pack table.

### Compose on LinuxONE, as run

The [container recipe](../deploy/containers/README.md) assumes the checkout is `~/sw/app` on Ubuntu LinuxONE. [SETUP](../deploy/SETUP.md) records that server's Python, apt libraries, database and data staging; it is an initial setup log, and its temporary anonymous-hub settings predate the [secured systemd ward](../security_v2/SECURITY.md).

1. Build the screens from the repository root: `cd web && npm ci && npm run build` (Node 22 per the README check).
2. On the build server, install Docker once, then log in again for group membership:

   ```bash
   sudo apt-get install -y docker.io docker-compose-v2 && sudo usermod -aG docker linux1
   ```

3. Set `SW_PACKS_DIR` in the shell to the absolute directory containing your verified twelve bed packs. If you built them into `data/packs` above, run `export SW_PACKS_DIR="$(pwd)/data/packs"` from the repository root. Then follow the checked-in commands:

   ```bash
   cd ~/sw/app/deploy/containers
   ./make-env.sh
   ./sync-frontend.sh
   docker compose build
   docker compose up -d
   curl -s 127.0.0.1:8001/api/health
   ./evidence.sh
   ```

`make-env.sh` creates the private database password and environment file. `sync-frontend.sh` copies the built screens so the non-root API can read them. The image includes the M2 artifacts; the pack builder is separate. `docker compose ps` shows api/hub/db health and plain `Up` for brain/sim/attacks. Inspect health's MQTT/database fields too. `evidence.sh` saves platform, status, resource, hardening, image and health captures; it does not run the ward or the security test.

The six services are api, brain, sim, attacks, hub and db. **Compose is a separate copy, not the complete agents-on deployment:** the checked-in hub permits anonymous access inside its container network, and only the web app is published to host loopback. It does not configure the systemd ward's TLS/dynamic-security accounts or start A1–A8, the network witness, Granite or the chip service. Do not expect its defaults to reproduce alerts, cut-off/Undo, reports or Granite briefings from run N. The [container evidence](evidence/CONTAINERS.md) and [security evidence](evidence/SECURITY.md) cover different configurations.

### What changes on a laptop / for the complete ward

On a laptop, use Docker with Compose available, work in this clone's `deploy/containers/` rather than the server's `~/sw/app`, and set `SW_PACKS_DIR` to your own absolute pack directory. The server's apt install and `linux1` group command are LinuxONE provisioning steps. Build locally: the [Dockerfile](../deploy/containers/Dockerfile) has no forced s390x platform, so a native laptop build is not LinuxONE proof. The NNPA chip hardware is a separate LinuxONE feature; [chip/README.md](../chip/README.md) describes CPU fallback. A from-scratch laptop Compose run/download time was not measured.

For the complete agents-on ward, use the systemd deployment on a provisioned LinuxONE host:

- [deploy/README.md](../deploy/README.md): `./deploy/deploy.sh --dry-run`, then `./deploy/deploy.sh`; needs your own SSH/sudo access and server environment/database. The dry run is offline; the real command builds, transfers and restarts services. It does not provision agents or the witness.
- [agents_v2/REPORT.md](../agents_v2/REPORT.md#run-on-the-server): install the fresh package, create private `agents2.env` from [the example](../deploy/agents2.env.example), create its state directories and install/start `sw-agents2`. The older `deploy/AGENTS.md` describes `sw-agents`; the current unit is [sw-agents2.service](../deploy/systemd/sw-agents2.service).
- [security_v2/SECURITY.md](../security_v2/SECURITY.md#server-installation-and-recovery): install the package, run `setup.py` and `verify.py` between demos, with the agent unit present; it provisions per-device accounts, TLS, containment credentials, adapters and `sw-net`. Follow its recovery instructions if provisioning order differs. Its historical `sw-agents` wording needs the current-unit correction in [DEMO-RUNBOOK](DEMO-RUNBOOK.md).
- [Granite setup](../deploy/granite/README.md): `run-granite.sh` in IBM's LinuxONE lab image and `SW_GRANITE_URL` for A8. Without a working/fact-checked response, the briefing is labelled template. [Chip setup](../chip/README.md#run) is separate on the TEST guest, shown only. Telegram needs your own token/chat configuration; screen alerts still work with Telegram off.

These linked recipes retain host-specific paths and dependency prerequisites. There is no checked-in single Compose command for the whole secured, agents-on demonstration.

## Open the UI and sign in

For local Compose, open `http://127.0.0.1:8001/`, then `/login`. For the existing systemd host, [the helper](demo/sw-demo.sh) runs `./docs/demo/sw-demo.sh tunnel` from the repository root, forwarding local port 8000 to the remote systemd API; it requires the configured SSH host/key (`SW_SSH_KEY` can override the key). Then open `http://127.0.0.1:8000/login`. Compose on a remote host needs a forward to its port 8001 instead: the helper's `tunnel` always targets remote 8000, even if `PORT` changes the local port.

Click a role card: no PIN is needed in default demo mode (`SW_DEMO_ROLE_LOGIN=true`). Each tab keeps its own session, so sign in separately in separate tabs. [UI role rules](../web/src/lib/domain.ts) and [routes](../web/src/App.tsx) define:

| Role card | Starts at | Screens to inspect |
|---|---|---|
| Central nurse | `/ward` | Ward → bed tile (`/bed/B03`, etc.), `/alerts`, `/briefing`, `/log` |
| Doctor / tele-ICU | `/census` | Census plus ward/bed, alerts, briefing and log |
| IT security | `/security` | Devices/fleet hunt, `/incident` → selected incident → report, ward/bed and log |
| Biomedical engineer | `/tickets` | Repair tickets and log |
| Demo operator | `/demo` | Run/reset controls and access to every screen; clinical writes remain nurse/doctor actions |

The landing and login pages need no session. The operator can inspect all screens, but use the nurse for Acknowledge/Patient OK and IT for security Undo. Tickets, briefing and Demo have no saved screenshot in the evidence folder; use these routes to inspect them live on the complete stack.

## Play the 20-minute ward

From the repository root, after the complete systemd ward and tunnel are running:

```bash
./docs/demo/sw-demo.sh health
./docs/demo/sw-demo.sh reset
./docs/demo/sw-demo.sh run 0
./docs/demo/sw-demo.sh watch 0
```

The helper implements `run <start_at_s>` for 0–1199, scenario `full_ward_script`, speed 1. For local Compose prefix each health/reset/run/watch invocation with `PORT=8001`; this changes the HTTP target, not the missing services. The Demo screen starts at zero and has no jump field. A new run replaces the current run; reset clears the prior demo state. The brain waits for the next run after reset ([deployment guide](../deploy/README.md)).

For a full run, follow the [measured runbook](DEMO-RUNBOOK.md) and compare with [WARD-RUN](evidence/WARD-RUN.md), rather than treating the older spec's expected verdicts as new results. T+ is ward time. The four human steps used in the saved full runs were: acknowledge B03 after escalation (~05:50), B05 Patient OK (~11:30), IT Undo of B05 (~15:30, after the replay ends), and B12 Patient OK (~18:00). Use separate role tabs. B04's false alarm remains EMERGENCY and B06's forged alarm can be BOTH: alarms are never suppressed. B03's recording ends shortly after the alarm, so film/inspect its red tile before it becomes offline with last values.

For shorter checks, [DEMO-RUNBOOK section 4](DEMO-RUNBOOK.md#4-recovery) gives these measured jumps. Times are after that run command, not newly measured here:

| Moment | Helper command | Runbook observation |
|---|---|---|
| B03 emergency / ladder | `./docs/demo/sw-demo.sh run 270` | Alert +36 s, red tile +39 s, step 2 about +65 s |
| B05 replay / cut-off | `./docs/demo/sw-demo.sh run 290` | Untrusted +313 s, cut off +333 s; Undo after +640 s |
| B07 attack + emergency | `./docs/demo/sw-demo.sh run 760` | DEVICE_ATTACK +73 s, BOTH + cut-off +86 s |
| B06 forged flatline | `./docs/demo/sw-demo.sh run 930` | BOTH + cut-off about +34–37 s |
| Granite briefing | `./docs/demo/sw-demo.sh run 1050` | Written +91 s; reload `/briefing`; template fallback is possible |

Start no later than about 350 s for B05: its replay needs the stream captured at T+06:00 during the same run. Starting at 560 was measured to fail with `attack_unavailable`. `run 270` is the runbook's continuous take through the later events; separate late jumps cannot substitute for a full run's history. End with `./docs/demo/sw-demo.sh reset`.

## Trace a result to its evidence

Use the [README evidence table](../README.md#read-the-logs-and-evidence) for file links. [Night run N](evidence/WARD-RUN.md#night-run-n-on-build-4348467-18-oct-2026-0042-ist--the-latest-build) follows build 4348467's network-witness fix; F1–F3 remain historical comparisons, including their B12 misses. Read each run's own timeline and metrics together. The N agent timeline logs A1–A8 actions, alerts and records, including A3 SHA-256 file digests and A5 draft/clock actions. It also includes events after T+20:00; do not count those in the 20-minute totals.

In the live UI, `/log` exposes actions; IT/operator can inspect incidents and the report through `/incident`. Saved evidence includes the incident/draft screenshots and logged hashes, not the underlying incident payload files. [A3 source](../agents_v2/sw_agents/agents/a3_evidence.py) and the [engine](../agents_v2/sw_agents/engine.py) show how snapshots and the append-only action log are written. [INTEROP](evidence/INTEROP.md) explains authenticated `GET /api/fhir/Bundle` and `/api/fhir/metadata`; its saved Bundle is a synthetic endpoint fixture, not a hospital export.

Read limitations beside results: M2 fatigue figures are advice only; robustness uses perturbed held-out recordings; 96-bed scale ran for 3 minutes without a 96-bed soak; the CNN is a second opinion without a demonstrated NNPA speed-up; the security 15/15 file is saved output. Re-running the live security probes interrupts the ward: [DEMO-RUNBOOK](DEMO-RUNBOOK.md#3-linuxone-proof-shots-terminal-c-on-the-server-outputs-captured-17-oct-2100-ist) gives the stop/test/restart procedure with the current agent unit. No live checks were run for this documentation update.
