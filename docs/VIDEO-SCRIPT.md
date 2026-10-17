# SentinelWard: 3-minute video script (v2, 17 Oct, build day)

Built from doc 15 v1.1, updated to what we actually built today. **[brackets] = fill in only with numbers measured in Phase 4.** Honesty rules: lab ward replaying real recordings (say so); IBM z17 / Telum II is verified on our server (machine type 9175, `nnpa` in /proc/cpuinfo), but say "our model runs on the AI chip" **only** if Phase 2's NNPA test succeeded; no IBM marketing numbers.

Rubric: 1 value + theme · 2 originality (all code written during the event) · 3 LinuxONE design + open-source AI, with screenshots of containers, security, scalability, compute · 4 clear video with a demo, under 3:00.

| Time | Scene (what is on screen) | Voice-over |
|---|---|---|
| 0:00-0:12 | Ward screen: 12 bed tiles, one turns red | "An ICU alarm goes off. Is it the patient, a loose sensor, or someone faking the monitor? Today, nobody can tell in time." |
| 0:12-0:30 | Simple graphic: three causes, one alarm | "Most ICU heart alarms are false: 88.8% in one large study (Drew 2014). And monitors send their data over the hospital network. Faking it has been shown in labs; no real hospital case is known yet. We built for it before it happens." |
| 0:30-0:52 | **LinuxONE terminal**, large font: `lscpu` (s390x, IBM z17 9175), `docker compose ps` (6 hardened containers), `systemctl status` of the services, `docker stats` | "Everything that decides runs here, on IBM LinuxONE: the message hub, six AI checks, the decision layer, the agents and the evidence store, in hardened containers. Patient data never leaves this machine. [If NNPA test passed: The alarm model even runs on the z17's built-in AI chip.]" |
| 0:52-1:15 | B03 real VT (ward script T+05:00): red tile, Telegram alert on a phone, no answer, step 2, acknowledged | "A real heart emergency. The verdict arrives [3.0] seconds after the monitor's alarm. If nobody answers in 30 seconds, the alert climbs the ladder: next nurse, then everyone." |
| 1:15-1:32 | B04 false asystole: "monitor says asystole" next to a live pulse, task "refit the ECG lead" | "Here the monitor says the heart stopped, but the pulse never did. A loose lead, not a cardiac arrest: one calm task instead of a crash call." |
| 1:32-1:58 | Fake flatline + cut-off: flat ECG beside a live pulse, network check flags a second sender, tile turns grey "UNTRUSTED, last good hh:mm" with the last trusted values, then **Undo** | "Now an attacker fakes a flatline. Heart and pulse disagree, and the network shows a stranger. The device is cut off at our own hub, but the patient is never blank: the last trusted values stay on screen, and a nurse checks by hand. Every automatic action can be undone with one click." |
| 1:58-2:15 | B07 BOTH: real VF during an attack, alert **and** cut-off | "The hardest case: a real emergency during an attack. Suspected tampering never hides a possible emergency." |
| 2:15-2:30 | B08 vs B09 pressure lines side by side | "One arterial line drifts; one patient's pressure really falls. Comparing each line with that patient's own cuff tells the AI which: re-zero the first, rush to the second." |
| 2:30-2:50 | Results table (Phase 4): M2 held-out scores per alarm type, attacks caught + delay, missed emergencies, time-to-safe, Blind Time, CPU/RAM for 12 beds; security test table all PASS | "Built in 24 hours on real ICU data: [M2 held-out score], [attacks caught], [0] missed emergencies, all on [x]% of one LinuxONE server." |
| 2:50-3:00 | End card: Team TessNova, repo link, "IBM Z Datathon 2026" | "SentinelWard. Patient, sensor, or hacker: answered in seconds." |

## Recording checklist
- Record each scene separately from the same full ward-script run; screen at 1440x900.
- Terminal font 20 pt+, dark theme; show the server hostname `tessnovabuild`.
- Phone: Telegram chat with @sentinelward_tessnova_bot visible for B03.
- Keep total under 2:58; voice calm and slow.

## Judge screenshots to capture (criterion 3)
1. `lscpu` + `/proc/sysinfo` + `grep nnpa /proc/cpuinfo` (compute, platform).
2. `docker compose ps` + `deploy/evidence/containers/hardening.txt` (containers, security).
3. `security_v2` live test table, all PASS (security).
4. `docker stats` / `top` during the 12-bed run + the scale test (scalability, compute).
5. M2 training log on LinuxONE + held-out results (AI/ML open source on LinuxONE).
