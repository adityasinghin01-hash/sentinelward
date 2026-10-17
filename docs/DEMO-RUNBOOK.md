# Demo recording runbook (≤ 3 min video, one person, Mac)

For recording `docs/VIDEO-SCRIPT.md` alone. Every timing below was measured on the live LinuxONE server on 17 Oct 2026 (20:45–21:20 IST) through the real API; nothing is copied from older runs unless it says so. "+N s" = seconds after you start the run. "T+mm:ss" = ward-script time (`docs/spec/12-ward-script.md`) = `start_at_s` + seconds since the run started.

Helper: `docs/demo/sw-demo.sh` (`tunnel`, `ssh`, `health`, `reset`, `run START`, `watch START`). The S12 Demo screen has no "start at" field: it always starts at T+00:00, so jumps use the helper (or the curl in section 4).

## Plan: one take, ~16 minutes
Start the full ward script at `start_at_s=270` and keep recording until the briefing (about +880 s). Every demo moment in the video happens in this one take, in this order. Cut the clips afterwards.

Why 270: B03's alarm is at T+05:00, and the brain needs about 15 s of data before its first verdict. Why not later: B05's replay attack replays B05's own T+06:00 stream, and the attacker only has what it captured during this run. Any start after T+06:00 means the attack never fires. Tested: start 560 logged `attack_unavailable: Actual replay source T+360s was not captured`, and B05 stayed NORMAL.

## 1. Pre-flight (do this 15 minutes before)
1. Terminal A (keep open): `./docs/demo/sw-demo.sh tunnel`. Leave it running. If it says "Address already in use", an old tunnel is still up, which is fine.
2. Terminal B: `./docs/demo/sw-demo.sh health`. You should see `"ok":true,"mqtt_connected":true,"db_ok":true,"storage":"postgresql"`. Then `./docs/demo/sw-demo.sh reset` (HTTP 202). After a reset, `beds_online` is 0 and the brain sleeps until the next run. That is normal.
3. Terminal C (for the proof shots, 20 pt+ font, prompt shows `tessnovabuild`): `./docs/demo/sw-demo.sh ssh`.
4. Chrome window, 1440x900 (View → turn off bookmarks bar; zoom 100%). Open three tabs. Each tab keeps its own login (sessionStorage), so log in each tab separately at `http://127.0.0.1:8000/login` and click the role card:
   - Tab 1 "Demo operator": opens `/demo`. You only need it if you prefer clicking Reset there.
   - Tab 2 "IT security": opens `/security`. Used for the cut-off feed and Undo (also `/log`).
   - Tab 3 "Central nurse": opens `/ward`. This is the main recording tab (`/ward`, `/bed/B03`, `/alerts`, `/briefing`).
5. Phone: Telegram open on the SentinelWard bot chat, screen-mirroring or a second camera ready. Priya, Tom and Dr Mehta all map to this one chat (server config: 1 unique chat of 3 recipients). So every alert (B03, B04, B09, B10, B06, B07 …) lands on this phone. Telegram counters after today's test runs: sent 52, edited 53, failed 0. I did not press the phone buttons in testing. The "On my way" button sends the same ack as the screen, but only the screen ack was measured.
6. Screen recorder (QuickTime → New Screen Recording, or OBS) at 1440x900. Do not record Terminal B. It is your stopwatch and cue sheet.

## 2. The take: action, wait, screen, click, expected result
Start the take: in Terminal B run `./docs/demo/sw-demo.sh run 270`, then at once `./docs/demo/sw-demo.sh watch 270`. The watch prints `T+mm:ss B03=… B05=… B06=… B07=… | open alerts: bed:VERDICT@ladder-step` every 3 s. Use it as your cue.

Measured timings come from two test runs: the B03 numbers from a run started at 270, everything after B03 from a full run started at 290 (shifted by 20 s here). The later events do not depend on the start point.

| Video line (VIDEO-SCRIPT) | When (+s after run 270 / T+) | Tab / screen | You do | Expected on screen (measured) |
|---|---|---|---|---|
| 0:21–0:34 "twelve beds…" | +15 s → +35 s (T+04:45–05:05) | Nurse `/ward` | Nothing; film the 12 tiles | 10–11 tiles NORMAL with live waves (B07 shows "No monitor connected yet" until T+09:00; B04 joined at T+01:30). Dataset names/table are added in the edit |
| 0:00–0:10 cold open + 0:47–1:01 "Bed three…" | Alert +36 s, tile red +39 s (T+05:06–05:09) | Nurse `/ward`, then click the B03 tile → `/bed/B03` (six checks incl. M2) | Watch the phone: step-1 message arrives | B03 EMERGENCY, high, "Monitor alarm remains active"; alert "Bed 3 — possible heart emergency. Go now." to Priya. Measured: +5–9 s after the T+05:00 alarm in jumped runs (+2 s in the full ward run 3) |
| ladder step 2 + ack | Step 2 ≈ +65 s (29 s after step 1) | Nurse `/alerts` (ladder 1→2), phone | On the phone press **On my way** after step 2 shows; or Tab 3 `/alerts` → **Acknowledge** | Alert `escalated` step 2 to Priya + Tom, then `acked`. Measured screen ack → `record_ack` in 3 s. Note: B03's recording ends at ~T+05:38 (+68–70 s); the tile then goes NO DATA / last values and the alert stays open until acked (ack at T+05:49 worked). Film the red tile before +68 s |
| (not in video) | +72 s → +360 s | — | Wait. Phone gets B10, B04, B09 alerts; that is expected | B10 TAMPERING + cut off (T+06:02/06:24), B04 EMERGENCY (held alarm), B09 EMERGENCY (cuff) |
| 1:01–1:22 "Bed five…" | Untrusted +333 s, tile TAMPERING +336 s, nurse alert +339 s, **cut off +353 s** (T+10:03–10:23) | Nurse `/bed/B05` (grey UNTRUSTED, last trusted values, six check scores); then IT `/security` (MON-05 cut off, attack feed) | Optional at ≈ +420 s (T+11:30): Nurse `/bed/B05` → **Patient OK** | "Old or unverified regressed sequence"; alert "Bed 5 — monitor can't be trusted. Check pulse and breathing by hand." Patient OK → bedside_check logged and alert acked in 3 s |
| (B05 Undo, same line) | Click only after **+660 s (T+15:30)** | IT `/log` (or Security feed) → row "Cut off MON-05 at the hub…" → **Undo** | Click Undo | In 3 s: `enable_client` "Re-enabled MON-05 at the hub (undo by staff:sam)", logged with `undoes`; bed NORMAL ~95 s later (+~760 s; ward run 3: 92 s). The replay runs until T+15:30. An earlier Undo was not tested and would likely trip the 20 s cut-off again |
| 1:22–1:38 "Bed seven…" | Untrusted +557 s, DEVICE_ATTACK +560 s, TAMPERING +569 s, BOTH alert +572 s, **BOTH tile + cut off +576 s** (T+13:47–14:06) | Nurse `/ward` → `/bed/B07` (red "GO NOW" banner), then IT `/log` | Nothing | "Message flood at 8–15 messages/s" → "Replay checked from sequence and sender" → BOTH high "Bed 7 — GO NOW. Do not trust the screen numbers…"; disable_client "after BOTH (conf 1.00)"; the alert is never closed (step 2 at +603 s) |
| 1:38–1:53 "Bed six…" | **BOTH + cut off +695 s** (T+16:05); forged flatline starts +690 s | Nurse `/bed/B06` from +685 s; then `/log` | Nothing | BOTH high, "Conflicting frame content…", cut off in the same poll (3 runs: +4 to +7 s after T+16:00). Not checked by eye: once untrusted, the bed page shows the *last trusted* waves, so the flat ECG next to a live pulse may only be visible for ~5 s at +690 s. Fallback: `docs/evidence/screens/08` |
| 1:53–2:03 briefing | Written +874 s (T+19:04) | Nurse `/briefing` | Reload the page after +875 s | `generated_by: "IBM Granite"`, measured in the 290 full run. Granite's text is fact-checked and sometimes rejected → "template" (see section 4) |
| end | +930 s (T+20:00) | — | `./docs/demo/sw-demo.sh reset` | Run over |

## 3. LinuxONE proof shots (Terminal C on the server; outputs captured 17 Oct 21:00 IST)
Record these before or after the take. None of them changes anything.

```bash
hostname                                    # tessnovabuild
uname -m; grep PRETTY /etc/os-release       # s390x / Ubuntu 24.04.4 LTS
lscpu | grep -E "Architecture|Machine type|CPU\(s\):|MHz|Hypervisor"
#   Architecture: s390x · CPU(s): 3 · Machine type: 9175 · CPU dynamic/static MHz: 5508
#   Hypervisor: z/VM 7.3.0 · Hypervisor vendor: IBM     ("Model name" is "-" here, so don't grep it)
grep -o -m1 -w nnpa /proc/cpuinfo           # nnpa   (Telum II on-chip AI)
systemctl is-active sw-api sw-brain sw-sim sw-attacks sw-agents2 sw-net mosquitto   # 7× active
cd ~/sw/app/deploy/containers && docker compose ps --format "table {{.Name}}\t{{.Status}}"
#   sentinelward-api-1 Up (healthy) · attacks-1 Up · brain-1 Up · db-1 Up (healthy) · hub-1 Up (healthy) · sim-1 Up
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"
#   idle stack: sim 54.7MiB/256MiB · attacks 15.5MiB/384MiB · api 71.8MiB/384MiB · brain 52.8MiB/768MiB
#   hub 1.6MiB/128MiB · db 157MiB/512MiB · granite 1.9GiB/2GiB  (all ≈0% CPU: the container copy is idle)
docker inspect granite --format "{{.Config.Image}} {{.State.Status}}"
#   registry.linuxone.cloud.marist.edu/l1cc/jupyterlab-image-s390x:latest running   (IBM Granite host)
cat ~/sw/app/security_v2/evidence/20261017T140649Z-security.md      # 15-row table, all PASS
grep -c "| PASS |" ~/sw/app/security_v2/evidence/20261017T140649Z-security.md   # 15
echo | openssl s_client -connect 127.0.0.1:8883 -tls1_3 2>/dev/null | grep "New, TLS"
#   New, TLSv1.3, Cipher is TLS_AES_256_GCM_SHA384
```

- The security live test was **not** re-run today. It needs the app services stopped (MON-03 probes kick the live simulator), so show the saved 15/15 file above. To re-run it live, do it before the take. It takes the ward down for its duration:
  `cd ~/sw/app && sudo systemctl stop sw-api sw-brain sw-sim sw-attacks sw-agents2 && SW_SECURITY_LIVE=1 ~/sw/.venv/bin/python security_v2/scripts/live_test.py --tls-host 148.100.112.19; sudo systemctl start sw-api sw-brain sw-sim sw-attacks sw-agents2 sw-net`. `security_v2/SECURITY.md` says `sw-agents`; the installed unit is `sw-agents2`. Always run the start part.
- Granite briefing: the `/briefing` screen at the end of the take shows "generated by IBM Granite". The scale (96 beds, 22.4%), NNPA CNN and results tables come from `docs/evidence/SCALE.md`, `ML-RESULTS.md` and `README.md`. Film them from the repo, not live.

## 4. Recovery
- Screens frozen or "disconnected": check Terminal A (tunnel). Restart it with `./docs/demo/sw-demo.sh tunnel` and reload the tab. If a tab goes back to the login screen, click the role again.
- Missed a moment: `./docs/demo/sw-demo.sh reset`, wait 5 s, then rerun just that segment with one of these jumps (all measured from the run click):

  | Segment | `run` | Then | Measured |
  |---|---|---|---|
  | B03 emergency + ladder | `run 270` | +36 s alert, step 2 ≈ +65 s, ack | alert +36 s, tile +39 s, screen ack logged +3 s |
  | B05 replay → cut-off | `run 290` (not later than ~350) | ≈5 min | untrusted +313 s, TAMPERING +316 s, alert +319 s, cut off +333 s; Undo after +640 s |
  | B07 attack → BOTH | `run 760` | ≈1.5 min | DEVICE_ATTACK +73 s, TAMPERING +77 s, BOTH + cut off +86 s |
  | B06 faked flatline | `run 930` | ≈40 s | BOTH + cut off +34–37 s (twice: +37 s, ~+32 s) |
  | Granite briefing | `run 1050` | ≈1.5 min, then reload `/briefing` | written +91 s by **IBM Granite**. `run 1080`: written +63 s but by **template** (Granite text rejected by the fact-checker: "mentions MON-11 which is not in the facts"). If you see "template", reset and run 1050 again |

  Without the helper: `TOK=$(curl -s -X POST -H 'Content-Type: application/json' -d '{"role":"operator"}' http://127.0.0.1:8000/api/session | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')`, then `curl -X POST -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' -d '{"scenario":"full_ward_script","speed":1,"start_at_s":270}' http://127.0.0.1:8000/api/demo/run`.
- A new `run` replaces the current one. You can also reset first so old alerts don't clutter the screens.
- `health` shows `mqtt_connected:false` or the API does not answer: on the server run `systemctl status sw-api sw-brain sw-agents2 mosquitto --no-pager`, then `sudo systemctl restart <the failed unit>` and reset. Not tested today (services were left running by rule).
- No Telegram: on the server, check `python3 -c "import json;print(json.load(open('/home/linux1/sw/agents2-data/status.json'))['telegram'])"`. `failed` should be 0. The screen alerts still work, so film `/alerts` instead.
- Briefing page says no briefing (503): A8 writes at T+19:00. Wait or use the 1050 jump.

## 5. If you only have 15 minutes
1. `sw-demo.sh tunnel` (Terminal A); `sw-demo.sh health` → ok true; `sw-demo.sh reset`.
2. Chrome 1440x900, tab 1 Central nurse `/ward`, tab 2 IT security; phone on Telegram.
3. Start recording, `sw-demo.sh run 930`: B06 BOTH + cut off at ≈ +35 s. Film `/bed/B06` from +25 s.
4. `reset`, `run 760`: B07 DEVICE_ATTACK +73 s → BOTH + cut off +86 s. Film `/bed/B07`, then IT `/log`.
5. `reset`, `run 270`: B03 red + phone alert at +36 s; press **On my way** on the phone after step 2 (~+65 s).
6. `reset`, `run 1050`: reload `/briefing` at +95 s and check it says IBM Granite.
7. Terminal C (`sw-demo.sh ssh`): `lscpu | grep -E "Architecture|Machine type|MHz|Hypervisor"`, `grep -o -m1 -w nnpa /proc/cpuinfo`.
8. `cd ~/sw/app/deploy/containers && docker compose ps`; `cat ~/sw/app/security_v2/evidence/20261017T140649Z-security.md`.
9. B05 replay + Undo needs a ≥5-minute run (`run 290`), so skip it and use `docs/evidence/screens/02` and `04`.
10. `reset` at the end. Edit the clips to the VIDEO-SCRIPT lines.
