# Resource use on LinuxONE (T10)

Captured 2026-10-17 14:27:26 UTC during a live 12-bed ward-script run (`raw/resources-now.txt`; `ps` per systemd service, load average 0.12/0.23/0.37 on 3 vCPUs).

| Service | CPU % | RSS |
|---|---|---|
| sw-brain (six checks + M2 trees, 12 beds) | 2.2% | 268 MiB |
| sw-api (backend + screens) | 2.1% | 79 MiB |
| sw-attacks (demo attacker) | 1.0% | 115 MiB |
| sw-sim (12 monitors) | 0.4% | 84 MiB |
| sw-agents2 (A1–A8) | 0.2% | 50 MiB |
| sw-net (network witness) | 0.1% | 24 MiB |
| mosquitto (hub) | 0.1% | 17 MiB |

The whole live ward (12 beds, six AI checks every 5 s per bed, agents, hub, database) uses a few percent of three z17 cores. Brain tick time per bed count: `SCALE.md`.
