"""One-command acceptance check for the live SentinelWard server (run ON the LinuxONE server).

    ~/sw/.venv/bin/python tests_system/acceptance.py [--start-run] [--listen 30] [--out tests_system/results]

Checks, each PASS / FAIL / NOT RUN with the reason (never a guessed result):
  services   every expected systemd unit is active
  health     /api/health reports MQTT + database OK
  flow       during --listen seconds: vitals, six scores and a verdict per streaming bed (5 s cadence)
  contract   every observed message passes sw_common.validate
  blank      no bed in /api/ward without readings or a last-trusted snapshot
  hub-auth   anonymous MQTT connect is refused (only meaningful once the hub is locked down)
  containers docker compose stack is up (if deploy/containers is in use)
Writes acceptance.json + acceptance.md to --out.
"""
import argparse
import json
import os
import subprocess
import threading
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

import paho.mqtt.client as mqtt
import sw_common

API = os.environ.get("SW_ACCEPT_API", "http://127.0.0.1:8000")
HUB = (os.environ.get("MQTT_HOST", "127.0.0.1"), int(os.environ.get("MQTT_PORT", "1883")))
UNITS = os.environ.get("SW_ACCEPT_UNITS", "sw-api sw-brain sw-sim sw-attacks sw-agents").split()
BACKEND_ENV = Path("/home/linux1/sw/security-v2/env/backend.env")


def result(name, status, detail):
    return {"check": name, "status": status, "detail": detail}


def http_json(path, method="GET", body=None, cookie=None):
    req = urllib.request.Request(API + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", "Origin": API,
                                          **({"Cookie": cookie} if cookie else {})})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, json.loads(r.read() or b"null"), r.headers.get("Set-Cookie")


def operator_cookie():
    _, _, cookie = http_json("/api/session", "POST", {"role": "operator"})
    return cookie.split(";", 1)[0] if cookie else None


def hub_credentials():
    # Once security_v2 is on, read the backend's read-mostly account (never printed).
    if BACKEND_ENV.exists():
        env = dict(line.split("=", 1) for line in BACKEND_ENV.read_text().split() if "=" in line)
        return env.get("MQTT_USER"), env.get("MQTT_PASS")
    return None, None


def check_services():
    bad = []
    for unit in UNITS:
        state = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True).stdout.strip()
        if state != "active":
            bad.append(f"{unit}={state or 'missing'}")
    return result("services", "FAIL" if bad else "PASS", ", ".join(bad) or f"{len(UNITS)} units active")


def check_health():
    try:
        _, h, _ = http_json("/api/health")
    except Exception as exc:  # noqa: BLE001 - report, never crash the whole check
        return result("health", "FAIL", f"/api/health unreachable: {exc}")
    ok = bool(h.get("mqtt_connected")) and bool(h.get("db_ok", h.get("storage") == "memory"))
    return result("health", "PASS" if ok else "FAIL", json.dumps({k: h.get(k) for k in ("status", "mqtt_connected", "db_ok", "storage")}))


def listen(seconds):
    counts = defaultdict(lambda: defaultdict(int))
    invalid = []
    lock = threading.Lock()

    def on_message(_c, _u, msg):
        try:
            body = json.loads(msg.payload or b"null")
        except ValueError:
            body = None
        if body is None:
            return
        errors = sw_common.validate(body)
        parsed = sw_common.parse_topic(msg.topic)
        with lock:
            if errors:
                invalid.append(f"{msg.topic}: {errors[0]}")
            if parsed and getattr(parsed, "bed_id", None):
                kind = parsed.kind if parsed.kind != "score" else f"score:{parsed.model}"
                counts[parsed.bed_id][kind] += 1

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"acceptance-{os.getpid()}")
    user, password = hub_credentials()
    if user:
        client.username_pw_set(user, password)
    client.on_message = on_message
    client.connect(*HUB, keepalive=30)
    client.subscribe([("ward/bed/+/vitals", 0), ("ward/bed/+/score/+", 1), ("ward/bed/+/verdict", 1)])
    client.loop_start()
    time.sleep(seconds)
    client.loop_stop()
    client.disconnect()
    return counts, invalid


def check_flow(counts, seconds):
    streaming = {b: c for b, c in counts.items() if c.get("vitals", 0) > 0}
    if not streaming:
        return result("flow", "NOT RUN", "no bed streamed vitals (start a demo run or use --start-run)")
    expected_windows = max(1, int(seconds // 5) - 2)
    short = []
    for bed, c in sorted(streaming.items()):
        models = [m for m in ("M1", "M2", "M3", "M4", "M5", "M6") if c.get(f"score:{m}", 0) < expected_windows]
        if models or c.get("verdict", 0) < expected_windows:
            short.append(f"{bed}(verdicts={c.get('verdict', 0)}, low={','.join(models) or '-'})")
    return result("flow", "FAIL" if short else "PASS",
                  "; ".join(short) or f"{len(streaming)} beds: vitals + 6 scores + verdict every 5 s")


def check_blank(cookie):
    try:
        _, ward, _ = http_json("/api/ward", cookie=cookie)
    except Exception as exc:  # noqa: BLE001
        return result("blank", "FAIL", f"/api/ward unreachable: {exc}")
    beds = ward.get("beds", ward if isinstance(ward, list) else [])
    def has_values(block):
        return isinstance(block, dict) and any(v is not None for k, v in block.items()
                                               if k in ("hr", "spo2", "systolic", "diastolic", "rr", "vitals"))

    # A bed is blank only when it shows neither current nor last-trusted values (offline beds that
    # never streamed in this run are reported, not failed: the simulator joins some beds late).
    blank = [b.get("bed_id") or b.get("id") for b in beds
             if b.get("connected", True) and not (has_values(b.get("vitals")) or has_values(b.get("latest"))
                                                  or has_values((b.get("last_trusted") or {}).get("vitals")))]
    return result("blank", "FAIL" if blank else "PASS", f"blank beds: {blank}" if blank else f"{len(beds)} beds, none blank")


def check_hub_auth():
    if not BACKEND_ENV.exists():
        return result("hub-auth", "NOT RUN", "hub not locked down yet (security_v2 not installed)")
    rc = {}
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"anon-probe-{os.getpid()}")
    client.on_connect = lambda c, u, f, reason, p: rc.setdefault("rc", reason)
    try:
        client.connect(*HUB, keepalive=10)
        client.loop_start(); time.sleep(3); client.loop_stop()
    except Exception as exc:  # noqa: BLE001
        return result("hub-auth", "PASS", f"anonymous connect refused ({exc})")
    refused = rc.get("rc") is not None and getattr(rc["rc"], "is_failure", True)
    return result("hub-auth", "PASS" if refused else "FAIL", f"anonymous connect reason={rc.get('rc')}")


def check_containers():
    compose = Path(__file__).resolve().parents[1] / "deploy/containers/compose.yaml"
    if not compose.exists() or subprocess.run(["which", "docker"], capture_output=True).returncode:
        return result("containers", "NOT RUN", "docker or compose file not present")
    ps = subprocess.run(["docker", "compose", "-f", str(compose), "ps", "--format", "json"], capture_output=True, text=True)
    if ps.returncode:
        return result("containers", "FAIL", ps.stderr.strip()[:200])
    rows = [json.loads(line) for line in ps.stdout.splitlines() if line.strip()]
    down = [r.get("Service") for r in rows if r.get("State") != "running"]
    if not rows:
        return result("containers", "NOT RUN", "compose stack not started")
    return result("containers", "FAIL" if down else "PASS", f"down: {down}" if down else f"{len(rows)} containers running")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-run", action="store_true", help="POST /api/demo/run as operator first")
    ap.add_argument("--start-at", type=int, default=270)
    ap.add_argument("--listen", type=int, default=30)
    ap.add_argument("--out", default="tests_system/results")
    args = ap.parse_args()

    checks = [check_services(), check_health()]
    cookie = None
    try:
        cookie = operator_cookie()
    except Exception as exc:  # noqa: BLE001
        checks.append(result("session", "FAIL", f"operator login failed: {exc}"))
    if args.start_run and cookie:
        http_json("/api/demo/run", "POST", {"scenario": "full", "speed": 1, "start_at_s": args.start_at}, cookie)
        time.sleep(12)  # let windows fill
    counts, invalid = listen(args.listen)
    checks.append(check_flow(counts, args.listen))
    checks.append(result("contract", "FAIL" if invalid else "PASS",
                         "; ".join(invalid[:5]) if invalid else "every observed message passed sw_common.validate"))
    checks.append(check_blank(cookie))
    checks.append(check_hub_auth())
    checks.append(check_containers())

    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    (out / "acceptance.json").write_text(json.dumps({"at": stamp, "checks": checks}, indent=2))
    lines = [f"# Acceptance check {stamp}", "", "| Check | Result | Detail |", "|---|---|---|"]
    lines += [f"| {c['check']} | {c['status']} | {c['detail']} |" for c in checks]
    (out / "acceptance.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    raise SystemExit(1 if any(c["status"] == "FAIL" for c in checks) else 0)


if __name__ == "__main__":
    main()
