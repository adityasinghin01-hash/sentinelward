# Open source and open data used by SentinelWard

Everything SentinelWard runs on is open source or open data. Every line of SentinelWard's own code
was written during the IBM Z Datathon 2026. Exact pinned versions: `deploy/requirements-server.txt`
(server), each package's `pyproject.toml`, and `web/package.json` (screens).

## Platform (IBM LinuxONE, s390x)

| Component | What we use it for | Link |
|---|---|---|
| Ubuntu 24.04 LTS (s390x) | Server operating system on IBM LinuxONE Community Cloud | https://ubuntu.com/download/server/s390x |
| Eclipse Mosquitto 2.0 | MQTT message hub; Dynamic Security plugin for per-device accounts and ACLs | https://mosquitto.org/ |
| PostgreSQL 16 | Backend database (readings, verdicts, actions, records, audit) | https://www.postgresql.org/ |
| Docker / Docker Compose | Hardened containers for every service | https://www.docker.com/ · https://docs.docker.com/compose/ |
| OpenSSL | TLS certificates for the hub's encrypted listener | https://www.openssl.org/ |
| systemd | Bare-metal service supervision | https://systemd.io/ |
| llama.cpp (via llama-cpp-python) | Runs IBM Granite on LinuxONE for the shift briefing | https://github.com/ggml-org/llama.cpp · https://github.com/abetlen/llama-cpp-python |
| IBM Granite | Language model that writes the shift-briefing prose from real facts | https://github.com/ibm-granite · https://huggingface.co/ibm-granite |
| IBM LinuxONE Community Cloud lab image (jupyterlab-image-s390x) | IBM's s390x image with Granite, llama.cpp and IBM's PyTorch/zDNN for the z17 AI chip | https://github.com/linuxone-community-cloud/jupyter-lab-ml |

## AI / ML and signal processing (Python)

| Library | What we use it for | Link |
|---|---|---|
| NumPy | Signals, windows, features | https://numpy.org/ |
| SciPy | Resampling (resample_poly), filters, peak detection | https://scipy.org/ |
| scikit-learn | Gradient-boosted trees for M2 ("is this alarm real?"), trained on LinuxONE | https://scikit-learn.org/ |
| pandas | Data tables during training and evaluation | https://pandas.pydata.org/ |
| WFDB for Python | Reading PhysioNet waveform records (2015 challenge, MIMIC, VTaC) | https://github.com/MIT-LCP/wfdb-python |
| vitaldb | Reading VitalDB surgery recordings (on the Mac; LinuxONE gets converted packs) | https://github.com/vitaldb/vitaldb-python |

## Services, messaging and web (Python)

| Library | What we use it for | Link |
|---|---|---|
| FastAPI | Backend REST API | https://fastapi.tiangolo.com/ |
| Uvicorn + websockets | ASGI server and the live WebSocket feed | https://www.uvicorn.org/ · https://websockets.readthedocs.io/ |
| Pydantic | Request/response validation | https://docs.pydantic.dev/ |
| Eclipse Paho MQTT (Python) | MQTT client for every service | https://github.com/eclipse-paho/paho.mqtt.python |
| psycopg 3 | PostgreSQL driver | https://www.psycopg.org/ |
| HTTPX | HTTP client (Telegram Bot API, Granite server, tests) | https://www.python-httpx.org/ |
| PyYAML | Ward script and bed configuration | https://pyyaml.org/ |
| pytest | Unit, integration and contract tests | https://pytest.org/ |

## Screens (TypeScript)

| Library | What we use it for | Link |
|---|---|---|
| React | Web app UI | https://react.dev/ |
| Vite | Build tool | https://vitejs.dev/ |
| TypeScript | Typed frontend code | https://www.typescriptlang.org/ |
| Vitest | Frontend unit tests | https://vitest.dev/ |
| Playwright | Screenshot and browser tests | https://playwright.dev/ |

## Open datasets

| Dataset | What we use it for | Link |
|---|---|---|
| PhysioNet/CinC Challenge 2015: Reducing False Arrhythmia Alarms in the ICU | Real alarm recordings for the ward (beds B03, B04, B07) and training/testing M2 | https://physionet.org/content/challenge-2015/1.0.0/ |
| VTaC: ventricular tachycardia alarms from ICU monitors | Real VT alarms with expert labels for training/testing M2 | https://physionet.org/content/vtac/1.0/ |
| MIMIC-III Waveform Database Matched Subset (sample) | Normal ICU background beds (B01, B02, B05, B06, B11, B12) | https://physionet.org/content/mimic3wdb-matched/1.0/ |
| VitalDB | Surgery recordings with arterial line and cuff for the drift beds (B08, B09, B10) | https://vitaldb.net/ |

## External service

| Service | What we use it for | Link |
|---|---|---|
| Telegram Bot API | Phone alerts in the demo (stand-in for a hospital messaging app) | https://core.telegram.org/bots/api |
