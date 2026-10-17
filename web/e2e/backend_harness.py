#!/usr/bin/env python3
"""Local screen-test publisher over the real backend; no external broker or database.

Run: /tmp/swa-venv/bin/python web/e2e/backend_harness.py
All synthetic observations enter Runtime.ingest with sw_common validation/topics.
The local bus confirms requests after a delay; it never claims real broker effects.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import math
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "common")]

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict
import uvicorn
from sw_api.app import create_app
from sw_api.config import Settings
from sw_common import (make_action, make_alert, make_net_features, make_record,
                       make_score, make_verdict, make_vitals, topic_for, validate)

SCENARIOS = {
    "B01": ("NORMAL", "Signals agree; monitoring continues.", .98),
    "B02": ("EMERGENCY", "Sustained tachycardia with matching pulse; check patient now.", .96),
    "B03": ("LOOSE_SENSOR", "SpO2 signal quality fell; check the finger probe.", .51),
    "B04": ("DRIFTING", "Blood pressure trend diverges from the recent baseline.", .64),
    "B05": ("NORMAL", "Stable rhythm and oxygen saturation.", .99),
    "B06": ("UNSURE", "Model evidence is inconclusive; bedside review requested.", .55),
    "B07": ("TAMPERING", "Repeated waveform segment and sequence replay detected.", .18),
    "B08": ("DEVICE_ATTACK", "Abnormal connection rate; local test isolation confirmed.", .12),
    "B09": ("BOTH", "Clinical deterioration and replay evidence occur together.", .21),
    "B10": ("LOOSE_SENSOR", "Intermittent ECG contact; inspect lead placement.", .59),
    "B11": ("NORMAL", "All six model checks are within expected limits.", .97),
    "B12": ("NORMAL", "Stable observations; routine monitoring.", .98),
}


class Control(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pause_bed: str | None = None
    resume_bed: str | None = None
    mqtt_connected: bool | None = None
    confirm_requests: bool | None = None


class LocalBus:
    """The only fake: an in-process publisher transport and explicit test agents."""

    def __init__(self):
        self.is_connected = True
        self.confirm_requests = True
        self.publisher = None
        self.tasks: set[asyncio.Task] = set()

    def subscribe(self, patterns, handler):
        self.handler = handler

    def connect(self, wait_s=0):
        return self.is_connected

    def stats(self):
        return {"invalid": 0}

    def close(self):
        self.is_connected = False

    def publish(self, message):
        errors = validate(message)
        if errors:
            raise ValueError(errors)
        if not self.is_connected:
            return False
        if self.confirm_requests and message["type"] in ("request", "demo_control"):
            task = asyncio.create_task(self.publisher.respond(copy.deepcopy(message)))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
        return True


class Publisher:
    def __init__(self, runtime, bus):
        self.runtime, self.bus = runtime, bus
        bus.publisher = self
        self.paused: set[str] = set()
        self.sequence = {bed: 0 for bed in SCENARIOS}
        self.origin = runtime.clock.ms()
        self.cutoff = self.origin - 31_000
        self.emitted = 0

    def ingest(self, message):
        if not self.runtime.ingest.process(message, topic_for(message)):
            raise RuntimeError(f"Harness message rejected: {message}")
        self.emitted += 1

    def record(self, kind, ident, by, data, ts=None):
        self.ingest(make_record(kind=kind, record_id=ident, by=by, data=data,
                                ts=self.runtime.clock.ms() if ts is None else ts))

    def observation(self, bed, ts, baseline=False, models=True):
        verdict, reason, trust = SCENARIOS[bed]
        if baseline:
            verdict, reason, trust = "NORMAL", "Trusted baseline before the test event.", .99
        number = int(bed[1:])
        emergency = verdict in ("EMERGENCY", "BOTH")
        hr = (146 if emergency else 69 + number) + math.sin(ts / 6000 + number) * 2
        spo2 = (89 if emergency else 98) + math.sin(ts / 12000 + number) * .5
        phase = ts / 1000 * hr / 60
        ecg, ppg = [], []
        for i in range(125):
            cycle = (phase + i / 125 * hr / 60) % 1
            ecg.append(round(.05 * math.sin(cycle * math.tau) + 1.2 * math.exp(-((cycle - .22) / .026) ** 2)
                             - .25 * math.exp(-((cycle - .27) / .025) ** 2)
                             + .16 * math.exp(-((cycle - .6) / .09) ** 2), 4))
            ppg.append(round(.5 + .4 * math.sin(cycle * math.tau - .8), 4))
        scores = {f"M{i}": .03 + i * .01 for i in range(1, 7)}
        elevated = {"LOOSE_SENSOR": ("M1",), "EMERGENCY": ("M2",), "BOTH": ("M2", "M4"),
                    "TAMPERING": ("M3", "M4"), "DEVICE_ATTACK": ("M5",), "DRIFTING": ("M6",),
                    "UNSURE": ("M1", "M3")}.get(verdict, ())
        scores.update({model: .94 if verdict != "UNSURE" else .52 for model in elevated})
        if models:
            window = ts // 5000 * 5000
            for model, score in scores.items():
                self.ingest(make_score(bed_id=bed, model=model, model_version="e2e-synthetic-v1",
                            window_start=window, score=score, label="flagged" if score > .5 else "clear",
                            reason=reason, extra={"source": "local-e2e-harness"}))
            self.ingest(make_verdict(bed_id=bed, window_start=window, verdict=verdict,
                        confidence=.95 if verdict != "UNSURE" else .54, trust=trust, scores=scores,
                        reasons=[reason], ts=ts,
                        last_trusted_ts=None if verdict in ("NORMAL", "EMERGENCY") else self.cutoff))
            attack = verdict in ("TAMPERING", "BOTH", "DEVICE_ATTACK")
            self.ingest(make_net_features(device_id=f"MON-{number:02d}", window_start=window,
                        msgs_per_s=24 if attack else 1, bytes_per_s=24000 if attack else 1800,
                        iat_mean_ms=42 if attack else 1000, iat_std_ms=65 if attack else 2,
                        payload_mean=1800, payload_std=12, senders=3 if attack else 1,
                        connects_per_s=4 if attack else 0, malformed=2 if attack else 0,
                        seq_gaps=3 if attack else 0, seq_repeats=8 if attack else 0, stale_ms=0))
        self.sequence[bed] += 1
        self.ingest(make_vitals(bed_id=bed, seq=self.sequence[bed], ts=ts, ecg=ecg, ppg=ppg,
                    hr=round(hr), spo2=round(spo2), rr=28 if emergency else 16,
                    nibp={"sys": 92 if emergency else 118 + number, "dia": 58 if emergency else 73,
                          "map": 69 if emergency else 89, "ts": ts},
                    monitor_alarm={"code": "TACHY", "priority": "high"} if emergency else None))

    def seed(self):
        self.origin = self.runtime.clock.ms()
        self.cutoff = self.origin - 31_000
        # Store real historical samples, including trusted pre-event samples.
        for seconds in range(60, -1, -1):
            ts = self.origin - seconds * 1000
            for bed in SCENARIOS:
                self.observation(bed, ts, baseline=seconds >= 31, models=seconds % 5 == 0 or seconds == 31)
        for bed, (verdict, reason, _) in SCENARIOS.items():
            if verdict != "NORMAL":
                self.ingest(make_alert(alert_id=f"alert_e2e_{bed}", bed_id=bed, verdict=verdict,
                            text=reason, to=[self.runtime.state.beds[bed].cfg.nurse],
                            ts=self.origin - 20_000))
        self.ingest(make_action(action_id="act_e2e_isolate_B08", by="A2", action="disable_client",
                    bed_id="B08", device_id="MON-08", undo_id="act_e2e_isolate_B08",
                    detail="Local test agent isolated MON-08 after an anomalous connection burst.",
                    ts=self.origin - 15_000))
        for bed in ("B07", "B08", "B09"):
            ident = f"inc_e2e_{bed}"
            content = {"source": "local-e2e-harness", "bed_id": bed,
                       "verdict": copy.deepcopy(self.runtime.state.beds[bed].verdict),
                       "note": "Synthetic local test evidence; no external packet capture."}
            blob = json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
            evidence = [{"evidence_id": f"ev_e2e_{bed}", "kind": "signal_snapshot",
                         "label": "Synthetic local test snapshot", "filename": f"{bed}-snapshot.json",
                         "captured_at": self.origin - 20_000, "captured_by": "A3", "source": "local-e2e-harness",
                         "size_bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest(),
                         "available": True, "verified": True, "content": content}]
            self.record("incident", ident, "A3", {"bed_id": bed, "device_id": f"MON-{bed[1:]}",
                        "status": "verified_available_context", "evidence": evidence,
                        "missing_context": ["pcap"], "pcap_available": False, "revision": 1,
                        "timeline": [{"ts": self.origin - 30_000, "kind": "verdict", "verdict": SCENARIOS[bed][0]}]},
                        self.origin - 20_000)
            fields = {"organisation": {"value": "SentinelWard demonstration ward", "status": "observed", "source": "local fixture"},
                      "description": {"value": SCENARIOS[bed][1], "status": "observed", "source": "synthetic verdict"},
                      "actions_taken": {"value": "Review evidence and confirm containment at bedside.", "status": "observed", "source": "local fixture"}}
            self.record("report", f"rep_e2e_{bed}", "A5", {"incident_id": ident, "bed_id": bed,
                        "status": "needs_review", "fields": fields, "evidence": evidence,
                        "observed_ts": self.origin - 30_000, "noticed_ts": self.origin - 20_000,
                        "deadline_ts": self.origin + 6 * 3600_000, "missing_fields": ["reporter_name", "phone"],
                        "checklist": {"facts_checked": False, "evidence_reviewed": False, "approved": False},
                        "narrative": {"text": "Synthetic replay evidence requires human review. No report has been sent.",
                                      "generator": "template"}})
        for bed in ("B03", "B04", "B10"):
            self.record("ticket", f"ticket_e2e_{bed}", "A6", {"bed_id": bed, "device_id": f"MON-{bed[1:]}",
                        "issue": SCENARIOS[bed][1], "status": "open", "note": "Awaiting biomedical inspection.",
                        "created_at": self.origin - 15_000, "source": "local-e2e-harness"})
        self.record("briefing", "brief_e2e", "A8", {"since": self.origin - 3600_000,
                    "narrative": {"generator": "template", "text": "Twelve beds are monitored. B02 and B09 need urgent bedside review. "
                    "Three security incidents are awaiting review; MON-08 is isolated. Three biomedical tickets remain open. "
                    "This is a local synthetic test shift."}})
        self.record("workload", "workload_e2e", "A7", {"since": self.origin - 7200_000,
                    "nurses": [{"staff_id": "staff:priya", "count": 47, "overloaded": True, "coverage": "partial"},
                               {"staff_id": "staff:tom", "count": 24, "overloaded": False, "coverage": "partial"}],
                    "basis": "distinct_screen_routed_alerts", "source": "local-e2e-harness"})

    async def run(self):
        while True:
            await asyncio.sleep(1)
            if self.bus.is_connected:
                ts = self.runtime.clock.ms()
                for bed in SCENARIOS:
                    if bed not in self.paused:
                        self.observation(bed, ts)

    async def respond(self, request):
        await asyncio.sleep(.35)
        if not self.bus.is_connected:
            return
        if request["type"] == "demo_control":
            # Production reset clears state first; next loop turn supplies a fresh run.
            if request["cmd"] == "reset":
                await asyncio.sleep(.01)
                self.seed()
            return
        action, target, bed = request["action"], request["target_id"], request.get("bed_id")
        now = self.runtime.clock.ms()
        ident = "act_e2e_" + request["request_id"]
        def result(actor, code, **extra):
            self.ingest(make_action(action_id=ident, by=actor, action=code, bed_id=bed,
                        device_id=f"MON-{bed[1:]}" if bed else None, approved_by=request["by"],
                        detail=f"Local test agent confirmed {action}: {request.get('note') or target}", ts=now, **extra))
        if action in ("ack_alert", "escalate_alert"):
            alert = self.runtime.state.alerts.get(target)
            if alert:
                self.ingest({**alert, "ts": now, "status": "acked" if action == "ack_alert" else "escalated",
                             "acked_by": request["by"] if action == "ack_alert" else alert.get("acked_by"),
                             "acked_ts": now if action == "ack_alert" else alert.get("acked_ts")})
                result("A1", "record_ack" if action == "ack_alert" else "escalate")
        elif action == "isolate_device":
            result("A2", "disable_client", undo_id=ident)
        elif action == "undo_action":
            original = self.runtime.store.actions.get(target)
            if original and original["action"] in ("disable_client", "set_bed_untrusted"):
                result("A2", "enable_client", undoes=target)
        elif action in ("contain_incident", "resolve_incident", "review_report"):
            record = self.runtime.state.records.get(target)
            if record:
                data = copy.deepcopy(record["data"])
                data["status"] = {"contain_incident": "contained", "resolve_incident": "resolved",
                                  "review_report": "ready_for_human_send"}[action]
                data["local_test_confirmation"] = {"request_id": request["request_id"], "by": request["by"], "ts": now}
                self.record(record["kind"], target, "A5" if action == "review_report" else "A3", data)
        elif action == "fleet_hunt":
            result("A4", "list_devices")


def build_app():
    bus = LocalBus()
    settings = Settings(pg_dsn="memory", frontend_dist=Path(os.environ.get("SW_FRONTEND_DIST", ROOT / "web" / "dist")))
    app = create_app(settings=settings, bus=bus)
    publisher = Publisher(app.state.runtime, bus)
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async with original_lifespan(application):
            publisher.seed()
            task = asyncio.create_task(publisher.run())
            try:
                yield
            finally:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
                for pending in list(bus.tasks):
                    pending.cancel()
                await asyncio.gather(*bus.tasks, return_exceptions=True)

    app.router.lifespan_context = lifespan

    # Insert test routes before any production SPA fallback route.
    @app.get("/api/e2e/control", include_in_schema=False)
    async def status(request: Request):
        if request.client.host not in ("127.0.0.1", "::1", "testclient"):
            raise HTTPException(403, "Local harness controls only")
        return {"synthetic": True, "paused_beds": sorted(publisher.paused),
                "mqtt_connected": bus.is_connected, "confirm_requests": bus.confirm_requests,
                "emitted_messages": publisher.emitted, "scenarios": {bed: value[0] for bed, value in SCENARIOS.items()}}

    @app.post("/api/e2e/control", include_in_schema=False)
    async def control(body: Control, request: Request):
        await status(request)
        for bed in (body.pause_bed, body.resume_bed):
            if bed is not None and bed not in SCENARIOS:
                raise HTTPException(422, "Unknown bed")
        if body.pause_bed:
            publisher.paused.add(body.pause_bed)
        if body.resume_bed:
            publisher.paused.discard(body.resume_bed)
        if body.mqtt_connected is not None:
            bus.is_connected = body.mqtt_connected
        if body.confirm_requests is not None:
            bus.confirm_requests = body.confirm_requests
        await app.state.runtime.tick()
        return await status(request)

    app.router.routes.sort(key=lambda route: 0 if getattr(route, "path", "").startswith("/api/e2e/") else 1)
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8012)
    args = parser.parse_args()
    uvicorn.run(build_app(), host="127.0.0.1", port=args.port, log_level="info")
