# SentinelWard

Team TessNova · IBM Z Datathon 2026 · Theme 1: real-time AI decisions on IBM LinuxONE.

SentinelWard watches simulated bedside monitors and decides, for every bed, whether an alarm means a real patient emergency, a faulty or drifting sensor, or tampered data. The patient is never shown blank.

## Folders

| Folder | What | Owner |
|---|---|---|
| `agents_v2/` | Fresh A1–A8 agents (merge pending) | Aditya |
| `web/` | Fresh React screens (merge pending) | Antara Gupta |
| `ml_v2/` | Fresh M2 models; brain/ runs the decision pipeline | Aditya Singhal |
| `security_v2/` | Fresh hub security, M5 network witness and device cut-off | Kartik |
| `deploy/`, `common/`, `data/`, `simulator/`, `backend/`, `tests_system/` | Server and hub setup, shared message package, data loader, ward simulator, backend + database, system tests (coming next) | Aditya Singh (lead) |

## Where each folder came from

Each teammate built their part in their own repo. This repo copies them in, one commit per part, authored by that teammate:

| Folder | Source repo | Commit copied |
|---|---|---|
| `agents/` | github.com/adityavijay3659-sketch/SentinelWard, branch `phase/6-verification` | `4ac8c8b` |
| `frontend/` | github.com/aragupta1225/sentinelward-frontend | `3de7377` |
| `ml/` | github.com/ADI238IND/sentinelward-ml, plus `components/` and the extra files from its `SentinelWard_M1-M4_M6_D_M5-review_20261017.zip` | `79e1ad1` |
| `security/` | github.com/kartikDevS/IBM_Datathon | `a6291f0` |
