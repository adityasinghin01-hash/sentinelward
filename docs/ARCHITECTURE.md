# SentinelWard architecture

Everything inside the IBM LinuxONE box runs on one IBM LinuxONE guest (IBM z17, s390x; `docs/evidence/PLATFORM.md`).

```mermaid
flowchart LR
  subgraph Ward["Ward (lab: replayed real ICU recordings)"]
    M["12 bedside monitors<br/>MON-01..12<br/>1 reading / bed / second"]
    X["Attacker (red-team test)<br/>replay · fake flatline · flood · drift"]
  end

  subgraph L1["IBM LinuxONE (z17, s390x)"]
    H["Message hub<br/>Mosquitto + Dynamic Security<br/>per-device accounts, TLS 1.3"]
    E["Network witness<br/>features per device / 5 s"]
    B["Brain: six AI checks every 5 s<br/>M1 sensor · M2 real alarm · M3 body match<br/>M4 replay · M5 network · M6 drift"]
    D["Decision layer + safety rule<br/>8 verdicts, trust, reasons"]
    A["Agents A1-A8<br/>alerts + ladder · cut-off/undo · evidence<br/>CERT-In draft · tickets · workload · briefing (IBM Granite)"]
    API["Backend API + live feed<br/>PostgreSQL 16"]
  end

  N["Central-station screens<br/>nurse · doctor · IT · biomed"]
  P["Phone alerts (Telegram)"]
  R["Bedside nurse<br/>Patient OK / NOT OK"]

  M --> H
  X -. same topics .-> H
  H --> E --> B
  H --> B --> D
  D --> A
  D --> API
  A --> API
  A -- cut off device --> H
  A --> P
  API --> N
  N -- buttons --> API
  R --> API
  API -- requests --> A
```

## The five safety rules (every part obeys them)
1. A patient is never shown blank (last trusted values stay, marked untrusted).
2. Suspected tampering never cancels an emergency (verdict BOTH = alert **and** cut-off).
3. Every automatic action is logged and can be undone with one click.
4. Nothing automatic touches treatment.
5. Official reports are drafted by an agent and sent by a person.

## Verdicts (precedence BOTH > EMERGENCY > TAMPERING > DRIFTING > LOOSE_SENSOR > DEVICE_ATTACK > UNSURE > NORMAL; `brain/README.md`)
| Verdict | Priority | Who hears |
|---|---|---|
| NORMAL | none | nobody |
| EMERGENCY | high | nurse now, escalation ladder |
| BOTH | high | nurse now **and** device cut off at once |
| TAMPERING | medium | bed untrusted + bedside hand-check at once; IT; device cut off after 20 s of sustained evidence |
| UNSURE | medium | bedside hand-check |
| DRIFTING | medium | bedside nurse + biomed ticket |
| LOOSE_SENSOR | low | bedside nurse: refit the sensor (the monitor alarm itself is never suppressed) |
| DEVICE_ATTACK | none for nurses | IT only |
