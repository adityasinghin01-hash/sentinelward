# Platform: everything runs on IBM LinuxONE

Raw capture: `raw/platform-20261017T1405Z.txt` (2026-10-17 14:05:56 UTC, build server `tessnovabuild`).

| Item | Value |
|---|---|
| Architecture | s390x, big-endian, 64-bit |
| Machine type | 9175 (IBM z17) |
| CPU flags | includes `nnpa` (Telum II on-chip AI accelerator), `vxe2`, `sort`, `dflt` |
| vCPUs / clock | 3 at 5,508 MHz |
| Caches | L2 108 MiB (3 instances), L3 360 MiB |
| Hypervisor | IBM z/VM 7.3.0 |
| OS | Ubuntu 24.04, kernel 6.8.0-124-generic s390x |
| Memory | 7.8 GiB (`free -m`, raw/resources-now.txt) |

What runs here, natively on s390x: the MQTT hub (Mosquitto, TLS 1.3, dynamic security), PostgreSQL 16, the brain (six checks + the M2 trees trained on this machine), the simulator replaying real PhysioNet/VitalDB data, the agents (A1–A8), the API + screens, IBM Granite (in IBM's LinuxONE lab image) for the shift briefing, and the full container stack. The NNPA was used for the CNN experiment (`ML-RESULTS.md`).
