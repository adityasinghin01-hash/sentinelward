#!/bin/bash
# SentinelWard demo helper for recording the video (Mac side). Needs bash, curl, python3, ssh.
#   ./docs/demo/sw-demo.sh tunnel          # SSH tunnel: http://127.0.0.1:8000 -> server API + screens (Ctrl-C to stop)
#   ./docs/demo/sw-demo.sh ssh             # shell on the LinuxONE guest (for lscpu / docker / security shots)
#   ./docs/demo/sw-demo.sh health          # GET /api/health
#   ./docs/demo/sw-demo.sh reset           # POST /api/demo/reset (operator)
#   ./docs/demo/sw-demo.sh run 270         # POST /api/demo/run full_ward_script, speed 1, start_at_s=270 (operator)
#   ./docs/demo/sw-demo.sh watch 270       # every 3 s: ward-script clock + B03/B05/B06/B07 verdicts + open alerts
# PORT (default 8000) picks the local tunnel port, e.g. PORT=18004 ./docs/demo/sw-demo.sh health
set -euo pipefail
HOST=linux1@148.100.112.19
KEY="${SW_SSH_KEY:-$HOME/.ssh/claudebuild.pem}"
PORT="${PORT:-8000}"
BASE="http://127.0.0.1:${PORT}"

token() {  # one-click role login; prints the session token
  curl -sf -X POST -H 'Content-Type: application/json' -d "{\"role\":\"$1\"}" "$BASE/api/session" |
    python3 -c 'import sys,json; print(json.load(sys.stdin)["token"])'
}

case "${1:-}" in
  tunnel) exec ssh -4 -i "$KEY" -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -L "${PORT}:127.0.0.1:8000" "$HOST" ;;
  ssh)    exec ssh -4 -i "$KEY" -o ServerAliveInterval=30 "$HOST" ;;
  health) curl -s "$BASE/api/health"; echo ;;
  reset)
    curl -s -w '  HTTP %{http_code}\n' -X POST -H "Authorization: Bearer $(token operator)" \
      -H 'Content-Type: application/json' -d '{}' "$BASE/api/demo/reset" ;;
  run)
    start="${2:?usage: run START_AT_S (0..1199)}"
    [[ "$start" =~ ^[0-9]+$ ]] && (( start < 1200 )) || { echo "start_at_s must be 0..1199" >&2; exit 2; }
    curl -s -w '  HTTP %{http_code}\n' -X POST -H "Authorization: Bearer $(token operator)" \
      -H 'Content-Type: application/json' \
      -d "{\"scenario\":\"full_ward_script\",\"speed\":1,\"start_at_s\":${start}}" "$BASE/api/demo/run"
    date '+Run clicked at %H:%M:%S (local). Ward-script clock T+ = start_at_s + seconds since then.' ;;
  watch)
    start="${2:?usage: watch START_AT_S (the value you passed to run)}"
    BASE="$BASE" TOK="$(token nurse)" START="$start" python3 - <<'EOF'
import json, os, time, urllib.request
base, tok, start, t0 = os.environ["BASE"], os.environ["TOK"], int(os.environ["START"]), time.time()
def get(p):
    r = urllib.request.Request(base + p, headers={"Authorization": "Bearer " + tok})
    with urllib.request.urlopen(r, timeout=10) as f: return json.load(f)
print("Clock starts now: start this watch right after 'run'. Ctrl-C to stop.")
while True:
    s = start + int(time.time() - t0)
    try:
        beds = {b["bed_id"]: b for b in get("/api/ward")["beds"]}
        alerts = [a for a in get("/api/alerts") if a["status"] in ("open", "escalated")]
        cols = "  ".join(f'{k}={beds[k]["verdict"] or "-"}{"/isolated" if beds[k]["isolated"] else ""}' for k in ("B03", "B05", "B06", "B07"))
        al = ", ".join(f'{a["bed_id"]}:{a["verdict"]}@{a["ladder_step"]}' for a in alerts[:5])
        print(f"T+{s//60:02d}:{s%60:02d}  {cols}  | open alerts: {al or 'none'}", flush=True)
    except Exception as e:
        print(f"T+{s//60:02d}:{s%60:02d}  poll failed: {e}", flush=True)
    time.sleep(3)
EOF
    ;;
  *) sed -n '2,9p' "$0"; exit 2 ;;
esac
