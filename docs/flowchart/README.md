# SentinelWard flowcharts

| File | What it shows |
|---|---|
| `flowchart.mmd` → `flowchart.svg`, `flowchart.png` | The whole system, left to right. 12 bedside monitors (the simulator replaying real PhysioNet / MIMIC-III / VitalDB recordings) and the red-team attacker publish to the secured Mosquitto hub (TLS 1.3, per-device accounts, deny-by-default ACLs, Dynamic Security). The network witness (extractor, `sw-net`) reads the broker log and feeds M5 with distinct client-ID counts per bed topic/window, not cryptographic identity of each frame. The brain runs six checks every 5 s (M1 sensor, M2 real emergency with trees trained on LinuxONE, M3 body match, M4 replay, M5 network, M6 drift), and the decision layer turns them into one of 8 verdicts. Verdicts go to agents A1-A8 and to the backend (FastAPI + WebSocket, PostgreSQL 16), which serves the 13 screens. A1 sends Telegram alerts with a ladder. A2 cuts a device off at the hub and can undo it. The blue band is everything that runs on the IBM LinuxONE z17 guest. Red marks the emergency path: M2 → A1 → Telegram. |
| `decision.mmd` → `decision.svg`, `decision.png` | What happens for one bed every 5 s: vitals → window assembler (10 s window every 5 s, 125 Hz) → M1-M6 scores (0..1, or null when not eligible) → the fixed precedence BOTH > EMERGENCY > TAMPERING > DRIFTING > LOOSE_SENSOR > DEVICE_ATTACK > UNSURE > NORMAL (first match wins; who gets told comes from `docs/ARCHITECTURE.md`) → one retained verdict with trust and up to 3 reasons → agents. |

Sources: `README.md`, `docs/ARCHITECTURE.md`, `docs/spec/00-contract-v1.2.md`, `brain/README.md`, `agents_v2/REPORT.md`, `security_v2/SECURITY.md`, `deploy/containers/README.md`, `docs/spec/R8-screens.md`.
The diagram describes the secured systemd ward. The separate six-container stack (api, brain, sim, attacks, hub, db) omits agents and the witness and permits anonymous internal MQTT (`docs/evidence/CONTAINERS.md`). Diagram emergency paths refer to active monitor alarms, not proof of detection of every future emergency after disconnection.

## Render

```sh
cd docs/flowchart
for f in flowchart decision; do
  npx -y @mermaid-js/mermaid-cli@11.4.2 -i $f.mmd -o $f.svg -b white
  npx -y @mermaid-js/mermaid-cli@11.4.2 -i $f.mmd -o $f.png -b white -w 1920 -s 2
done
```
