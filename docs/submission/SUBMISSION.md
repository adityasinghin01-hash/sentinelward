# Submission copy sheet

**Title:** `[TessNova_IBM Z Datathon 2026 Project]`

**Description:** SentinelWard helps a care team distinguish patient emergencies, sensor faults and possible monitor tampering. It replays recordings from four public datasets in a 12-bed lab ward on IBM LinuxONE. Six checks and fixed safety rules produce explanations, alerts and reversible device cut-offs while active monitor alarms retain emergency precedence. Its alarm model was trained on LinuxONE; a separate AI-chip model provides a shown-only second opinion. This is a laboratory prototype, not a clinical device.

**Repository (public submission URL):** https://github.com/adityasinghin01-hash/sentinelward · [MIT License](../../LICENSE) (team code; upstream terms remain separate).

**Video:** VIDEO_URL_TBD

**Optional flowcharts:** [System](../flowchart/flowchart.png) · [Decision](../flowchart/decision.png).

## Evidence map

Saved runs and their limits; these are separate cohorts, not a new live verification.

| Judging criterion | Evidence (1–2 files per row) |
|---|---|
| Value and theme: replayed ward outcomes | [RESULTS-MANIFEST.md](../evidence/RESULTS-MANIFEST.md), [WARD-RUN.md](../evidence/WARD-RUN.md): N 12/12 beds; one post-fix run |
| Originality and implementation: trained alarm model | [ML-RESULTS.md](../evidence/ML-RESULTS.md), [brain/README.md](../../brain/README.md): held-out results, six checks and fixed safety rules |
| LinuxONE design: containers and security | [CONTAINERS.md](../evidence/CONTAINERS.md): 137/137 auth checks; [SECURITY.md](../evidence/SECURITY.md): systemd ward 15/15. Containers have no agents/witness, internal plaintext MQTT; authenticated replay only 40 seconds |
| LinuxONE design: scale and AI compute | [SCALE.md](../evidence/SCALE.md): 96 beds in short runs, no soak; [ML-RESULTS.md](../evidence/ML-RESULTS.md): LinuxONE training and shown-only NNPA model; no demonstrated chip speed-up |
| Clarity and demo | [JUDGE-GUIDE.md](JUDGE-GUIDE.md), [VIDEO-SCRIPT.md](../VIDEO-SCRIPT.md): evidence navigation and planned narration; video must show the LinuxONE instance and model |

## Open-source and data links

Links copied from [README sources](../../README.md#sources--open-source); uses and manifests: [OPEN-SOURCE.md](../OPEN-SOURCE.md). Dataset access/reuse follows provider terms.

- **Data:** [PhysioNet/CinC Challenge 2015](https://physionet.org/content/challenge-2015/1.0.0/), [VTaC](https://physionet.org/content/vtac/1.0/), [MIMIC-III Waveform Database Matched Subset](https://physionet.org/content/mimic3wdb-matched/1.0/), [VitalDB](https://vitaldb.net/).
- **Platform and model:** [Ubuntu s390x](https://ubuntu.com/download/server/s390x), [Eclipse Mosquitto](https://mosquitto.org/), [PostgreSQL](https://www.postgresql.org/), [Docker](https://www.docker.com/), [Compose](https://docs.docker.com/compose/), [OpenSSL](https://www.openssl.org/), [systemd](https://systemd.io/), [IBM Granite](https://github.com/ibm-granite), [llama.cpp](https://github.com/ggml-org/llama.cpp), [llama-cpp-python](https://github.com/abetlen/llama-cpp-python), [IBM's LinuxONE lab image](https://github.com/linuxone-community-cloud/jupyter-lab-ml), [PyTorch](https://pytorch.org/).
- **Python libraries:** [NumPy](https://numpy.org/), [SciPy](https://scipy.org/), [scikit-learn](https://scikit-learn.org/), [WFDB](https://github.com/MIT-LCP/wfdb-python), [vitaldb](https://github.com/vitaldb/vitaldb-python), [FastAPI](https://fastapi.tiangolo.com/), [Pydantic](https://docs.pydantic.dev/), [Uvicorn](https://www.uvicorn.org/), [websockets](https://websockets.readthedocs.io/), [Paho MQTT](https://github.com/eclipse-paho/paho.mqtt.python), [psycopg](https://www.psycopg.org/), [HTTPX](https://www.python-httpx.org/), [PyYAML](https://pyyaml.org/), [pytest](https://pytest.org/).
- **Web libraries and tools:** [React](https://react.dev/), [React Router](https://reactrouter.com/), [Vite](https://vite.dev/), [Zustand](https://github.com/pmndrs/zustand), [uPlot](https://github.com/leeoniya/uPlot), [jsPDF](https://github.com/parallax/jsPDF), [Vitest](https://vitest.dev/), [TypeScript](https://www.typescriptlang.org/), [Lucide](https://lucide.dev/), [IBM Plex fonts via Fontsource](https://fontsource.org/fonts/ibm-plex-sans), [Testing Library](https://testing-library.com/), [jsdom](https://github.com/jsdom/jsdom), [Playwright](https://playwright.dev/), [axe-core](https://github.com/dequelabs/axe-core).
- **Demo messaging:** [Telegram Bot API](https://core.telegram.org/bots/api).

## Team and honest limits

**TessNova:** Aditya Singh, Aditya Singhal, Aditya, Kartik, Antara Gupta.

- Lab replay prototype; not approved for clinical use.
- Confidence and trust scores are uncalibrated heuristics.
- Alarm-fatigue results are advice only; monitor alarms still sound, and per-type held-out sets are small.
- Scale evidence stops at short 96-bed runs; no 96-bed soak was run.
