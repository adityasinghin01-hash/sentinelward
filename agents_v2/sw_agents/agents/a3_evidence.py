"""A3 evidence: per-bed ring buffer of the last 10 min, frozen into files with SHA-256, plus a timeline.

One unresolved incident per bed (the backend resolves /api/incidents/<bed> to exactly one).
Files are written once and never changed, so re-hashing them later proves they are untouched.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from collections import deque
from pathlib import Path

from sw_common import device_for_bed

from ..engine import Agent, clean_text

log = logging.getLogger("sw_agents.a3")
TRIGGERS = frozenset({"TAMPERING", "BOTH", "DEVICE_ATTACK"})


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class A3Evidence(Agent):
    id = "A3"

    def __init__(self, engine) -> None:
        super().__init__(engine)
        self.root = Path(engine.s.state_dir) / "evidence"
        self.reset()

    def reset(self) -> None:
        self.buffers: dict[str, deque] = {}
        self.open: dict[str, dict] = {}        # bed -> incident data (unresolved)
        self.incidents: dict[str, dict] = {}   # incident_id -> data
        self.streak: dict[str, int] = {}

    # ------------------------------------------------------------------ buffer
    def _buffer(self, bed: str, msg: dict) -> None:
        buf = self.buffers.setdefault(bed, deque(maxlen=4000))
        now = self.e.now()
        buf.append((now, msg))
        horizon = now - int(self.e.s.evidence_window_s * 1000)
        while buf and buf[0][0] < horizon:
            buf.popleft()

    def on_event(self, name: str, data: dict) -> None:
        bed = data.get("bed_id")
        if name in ("in_verdict", "in_score", "in_bedside", "in_request", "alert", "action") and isinstance(bed, str):
            self._buffer(bed, dict(data))
        if name == "record" and data.get("kind") == "report" and data.get("by") == "A5":
            inc = self.incidents.get(data["data"].get("incident_id"))
            if inc is not None and inc.get("report_id") != data["record_id"]:
                inc["report_id"] = data["record_id"]
                self._publish(inc)
            return
        if bed not in self.open:
            return
        inc = self.open[bed]
        if name == "action" and data.get("by") in ("A1", "A2", "A4"):
            self._timeline(inc, data["ts"], f"{data['by']} {data['action']}: {data['detail']}")
        elif name == "alert" and data.get("status") in ("open", "acked", "escalated", "closed"):
            last = inc.setdefault("_alert_state", {})
            if last.get(data["alert_id"]) != (data["status"], data["ladder_step"]):
                last[data["alert_id"]] = (data["status"], data["ladder_step"])
                who = f" by {data['acked_by']}" if data.get("acked_by") else ""
                self._timeline(inc, data["ts"], f"Alert {data['alert_id']} {data['status']}{who} (step {data['ladder_step']}, {data['priority']})")
        elif name == "in_bedside":
            self._timeline(inc, data["ts"], f"Bedside check: {data['result']} by {data['by']}")

    # ------------------------------------------------------------------ incidents
    def on_verdict(self, v: dict) -> None:
        bed, verdict = v["bed_id"], v["verdict"]
        if verdict not in TRIGGERS:
            self.streak[bed] = 0
            return
        self.streak[bed] = self.streak.get(bed, 0) + 1
        inc = self.open.get(bed)
        if inc is not None:
            if inc["verdict"] != verdict:
                inc["verdict"] = verdict
                self._timeline(inc, v["ts"], f"Verdict now {verdict} (conf {v['confidence']:.2f})")
            return
        if verdict != "BOTH" and v["confidence"] < self.e.s.a2_min_confidence and self.streak[bed] < self.e.s.confirm_verdicts:
            return
        self._open_incident(v)

    def _write(self, folder: Path, name: str, lines: list) -> dict:
        path = folder / name
        payload = "".join(json.dumps(x, separators=(",", ":"), sort_keys=True, ensure_ascii=False) + "\n" for x in lines)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        return {"name": name, "bytes": path.stat().st_size, "sha256": sha256_file(path),
                "captured_at": self.e.now(), "path": f"evidence/{folder.name}/{name}"}

    def _open_incident(self, v: dict) -> None:
        bed = v["bed_id"]
        device = device_for_bed(bed)
        inc_id = self.e.new_id("inc")
        now = self.e.now()
        snap = [{"received_ts": t, "message": m} for t, m in self.buffers.get(bed, ())]
        timeline = []
        if v.get("last_trusted_ts"):
            timeline.append({"ts": v["last_trusted_ts"], "event": "Last trusted data (verdict.last_trusted_ts)"})
        timeline.append({"ts": v["ts"], "event": f"Detected: {v['verdict']} (conf {v['confidence']:.2f})"})
        for t, m in self.buffers.get(bed, ()):
            if m.get("type") == "action" and m.get("by") in ("A1", "A2"):
                timeline.append({"ts": m["ts"], "event": f"{m['by']} {m['action']}: {m['detail']}"})
        inc = {"incident_id": inc_id, "bed_id": bed, "device_id": device, "status": "open", "verdict": v["verdict"],
               "opened_ts": now, "detected_ts": v["ts"], "attack_start_ts": v.get("last_trusted_ts"),
               "reasons": [clean_text(r, 120) for r in (v.get("reasons") or [])[:3]], "evidence": [],
               "timeline": sorted(timeline, key=lambda e: e["ts"]), "report_id": None}
        self.open[bed] = inc
        self.incidents[inc_id] = inc
        folder = self.root / inc_id
        try:
            folder.mkdir(parents=True, exist_ok=False, mode=0o700)
            files = [self._write(folder, "messages.jsonl", snap),
                     self._write(folder, "verdicts.jsonl", [s for s in snap if s["message"].get("type") == "verdict"]),
                     self._write(folder, "timeline.json", inc["timeline"])]
            self.e.act("A3", "snapshot_files", bed_id=bed, device_id=device,
                       detail=f"Incident {inc_id}: froze {len(snap)} messages (last {int(self.e.s.evidence_window_s // 60)} min) "
                              f"of {bed} into {len(files)} files")
            for f in files:
                inc["evidence"].append(f)
                self.e.act("A3", "hash_file", bed_id=bed, device_id=device,
                           detail=f"{inc_id}/{f['name']}: {f['bytes']} bytes, sha256 {f['sha256']}")
        except OSError as exc:
            log.error("A3 evidence write failed: %s", type(exc).__name__)
            self.e.act("A3", "snapshot_files", bed_id=bed, device_id=device, result="failed",
                       detail=f"Incident {inc_id}: evidence files could not be written ({type(exc).__name__})")
        self.e.act("A3", "write_timeline", bed_id=bed, device_id=device,
                   detail=f"Incident {inc_id} timeline started with {len(inc['timeline'])} events")
        self._publish(inc)
        self.e.emit("incident_opened", self.public(inc))

    def public(self, inc: dict) -> dict:
        return {k: v for k, v in inc.items() if not k.startswith("_")}

    def _publish(self, inc: dict) -> None:
        self.e.publish_record("A3", "incident", inc["incident_id"], self.public(inc))

    def _timeline(self, inc: dict, ts: int, event: str) -> None:
        inc["timeline"].append({"ts": ts, "event": clean_text(event, 300)})
        inc["timeline"] = inc["timeline"][-200:]
        self._publish(inc)

    def verify(self, incident_id: str) -> bool:
        """Re-hash every evidence file; True if all match."""
        inc = self.incidents.get(incident_id)
        if not inc or not inc["evidence"]:
            return False
        return all(sha256_file(Path(self.e.s.state_dir) / f["path"]) == f["sha256"] for f in inc["evidence"])

    # ------------------------------------------------------------------ requests
    def _find(self, req: dict) -> dict | None:
        target = req["target_id"]
        inc = self.incidents.get(target) or self.open.get(target)
        if inc is None:
            self.e.refuse(req, "unknown incident")
        return inc

    def contain_request(self, req: dict) -> None:
        inc = self._find(req)
        if inc is None:
            return
        if inc["status"] == "resolved":
            return self.e.refuse(req, "incident already resolved")
        a2 = self.e.agents.get("A2")
        started = a2.contain(inc["bed_id"], f"contain_incident by {req['by']}", approved_by=req["by"]) if a2 else False
        inc["status"] = "contained"
        self.e.act("A3", "write_timeline", bed_id=inc["bed_id"], device_id=inc["device_id"], approved_by=req["by"],
                   detail=f"Incident {inc['incident_id']} marked contained by {req['by']}"
                          + ("" if started else " (device was already cut off or A2 unavailable)"))
        self._timeline(inc, self.e.now(), f"Contained by {req['by']}")

    def resolve_request(self, req: dict) -> None:
        inc = self._find(req)
        if inc is None:
            return
        if inc["status"] == "resolved":
            return self.e.refuse(req, "incident already resolved")
        inc.update(status="resolved", resolved_by=req["by"], resolved_ts=self.e.now(), resolution_note=clean_text(req.get("note"), 300))
        if self.open.get(inc["bed_id"]) is inc:
            del self.open[inc["bed_id"]]
        self.e.act("A3", "write_timeline", bed_id=inc["bed_id"], device_id=inc["device_id"], approved_by=req["by"],
                   detail=f"Incident {inc['incident_id']} resolved by {req['by']}")
        self._timeline(inc, self.e.now(), f"Resolved by {req['by']}")

    def snapshot(self) -> dict:
        return {"open": {b: i["incident_id"] for b, i in self.open.items()}, "total": len(self.incidents)}
