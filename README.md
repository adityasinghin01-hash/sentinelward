# SentinelWard

Team TessNova · IBM Z Datathon 2026 · Theme 1: real-time AI decisions on IBM LinuxONE.

SentinelWard watches simulated bedside monitors and decides, for every bed, whether an alarm means a real patient emergency, a faulty or drifting sensor, or tampered data. The patient is never shown blank.

## Folders

| Folder | What | Owner |
|---|---|---|
| `agents/` | Agent engine, alerts (A1), reports (A5), tickets (A6), workload (A7), briefing (A8), M6 drift watcher, IBM Granite writer | Aditya |
| `frontend/` | The 13 web screens and Telegram templates | Antara Gupta |
| `ml/` | M1–M4 models, M6 drift monitor, decision layer (D) | Aditya Singhal |
| `security/` | Hub security, attack scripts, M4 replay, M5 network witness, device cut-off | Kartik |
| `deploy/`, `common/`, `data/`, `simulator/`, `backend/`, `tests_system/` | Server and hub setup, shared message package, data loader, ward simulator, backend + database, system tests (coming next) | Aditya Singh (lead) |

## Where each folder came from

Each teammate built their part in their own repo. This repo copies them in, one commit per part, authored by that teammate:

| Folder | Source repo | Commit copied |
|---|---|---|
| `agents/` | github.com/adityavijay3659-sketch/SentinelWard, branch `phase/6-verification` | `4ac8c8b` |
| `frontend/` | github.com/aragupta1225/sentinelward-frontend | `3de7377` |
| `ml/` | github.com/ADI238IND/sentinelward-ml, plus `components/` and the extra files from its `SentinelWard_M1-M4_M6_D_M5-review_20261017.zip` | `79e1ad1` |
| `security/` | github.com/kartikDevS/IBM_Datathon | `a6291f0` |
