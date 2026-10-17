"""A5 CERT-In draft: on every incident, a draft with the form fields and a 6-hour clock.

It NEVER sends. There is no send code here: mark_report_sent is a person's action only (backend).
Empty fields are listed in data.missing_fields for a person to fill. DPDP breach notice is
described as applying from 13 May 2027, not now.
"""
from __future__ import annotations

from ..clock import iso
from ..engine import Agent

CLOCK_MS = 6 * 3600 * 1000
KIND = {"TAMPERING": "Data tampering on a networked patient monitor (forged/replayed readings suspected)",
        "BOTH": "Data tampering on a networked patient monitor during a possible patient emergency",
        "DEVICE_ATTACK": "Network attack on a patient monitor (scan/flood suspected)"}


class A5Report(Agent):
    id = "A5"

    def __init__(self, engine) -> None:
        super().__init__(engine)
        self.reset()

    def reset(self) -> None:
        self.reports: dict[str, dict] = {}       # report_id -> data
        self.by_incident: dict[str, str] = {}

    def _actions_taken(self, inc: dict) -> list[str]:
        return [f"{self.e.hms(e['ts'])} {e['event']}" for e in inc["timeline"]
                if e["event"].startswith(("A2 ", "A3 ", "A4 ", "Contained", "Resolved"))][-20:]

    def _draft(self, inc: dict, report_id: str, old: dict | None) -> dict:
        s = self.e.s
        model = s.device_models.get(inc["device_id"])
        data = {
            "report_id": report_id, "incident_id": inc["incident_id"], "bed_id": inc["bed_id"],
            "device_id": inc["device_id"], "status": "draft", "form": "CERT-In incident reporting form",
            "send_to": "incident@cert-in.org.in", "sent": False,
            "sending": "Never sent by SentinelWard. A person reviews, sends it by email and marks it sent.",
            "reporter_name": s.reporter_name, "organisation": s.organisation, "reporter_email": s.reporter_email,
            "reporter_phone": s.reporter_phone, "sector": "Health",
            "occurred_ts": inc.get("attack_start_ts"), "noticed_ts": inc["detected_ts"],
            "occurred_at": iso(inc["attack_start_ts"]) if inc.get("attack_start_ts") else None,
            "noticed_at": iso(inc["detected_ts"]),
            "incident_type": KIND.get(inc["verdict"], inc["verdict"]),
            "affected_system": {"device_id": inc["device_id"], "hardware_model": model, "ip_address": None,
                                "host_name": inc["device_id"], "os_version": None, "last_patched": None},
            "physical_location": f"{s.ward_name}, bed {inc['bed_id']}",
            "critical_to_mission": "Yes: patient monitoring",
            "symptoms": list(inc.get("reasons") or []),
            "actions_taken": self._actions_taken(inc),
            "evidence": [{"name": f["name"], "sha256": f["sha256"]} for f in inc.get("evidence", [])],
            "clock_started_ts": inc["detected_ts"], "clock_deadline_ts": inc["detected_ts"] + CLOCK_MS,
            "clock_deadline_at": iso(inc["detected_ts"] + CLOCK_MS),
            "dpdp_note": "DPDP breach notice: will apply from 13 May 2027; not required today. Draft prepared.",
        }
        data["missing_fields"] = [k for k in ("reporter_name", "organisation", "reporter_email", "reporter_phone", "occurred_ts")
                                  if data[k] is None] + [f"affected_system.{k}" for k, v in data["affected_system"].items() if v is None]
        return data

    def on_event(self, name: str, data: dict) -> None:
        if name == "incident_opened":
            self._create(data)
        elif name == "record" and data.get("kind") == "incident" and data.get("by") == "A3":
            rid = self.by_incident.get(data["record_id"])
            rep = self.reports.get(rid) if rid else None
            if rep is None or rep["status"] != "draft":
                return  # after review starts, A5 never overwrites a person's edits
            new = self._draft(data["data"], rid, rep)
            if new != rep:
                self.reports[rid] = new
                self.e.publish_record("A5", "report", rid, new)

    def _create(self, inc: dict) -> None:
        if inc["incident_id"] in self.by_incident:
            return
        rid = self.e.new_id("rp")
        data = self._draft(inc, rid, None)
        self.reports[rid] = data
        self.by_incident[inc["incident_id"]] = rid
        self.e.act("A5", "draft_report", bed_id=inc["bed_id"], device_id=inc["device_id"],
                   detail=f"CERT-In draft {rid} for incident {inc['incident_id']}; {len(data['missing_fields'])} fields "
                          f"need a person; never sent automatically")
        self.e.act("A5", "start_clock", bed_id=inc["bed_id"], device_id=inc["device_id"],
                   detail=f"CERT-In 6 h clock for {rid}: deadline {self.e.hm(data['clock_deadline_ts'])} "
                          f"({data['clock_deadline_at']})")
        self.e.publish_record("A5", "report", rid, data)

    def review_request(self, req: dict) -> None:
        rid = req["target_id"]
        if rid not in self.reports:
            rid = self.by_incident.get(rid, rid)
        rep = self.reports.get(rid)
        if rep is None:
            return self.e.refuse(req, "unknown report")
        if rep["status"] != "draft":
            return self.e.refuse(req, f"report is already {rep['status']}")
        rep = dict(rep, status="in_review", review_requested_by=req["by"], review_requested_ts=self.e.now())
        self.reports[rid] = rep
        self.e.act("A5", "draft_report", bed_id=rep["bed_id"], device_id=rep["device_id"], approved_by=req["by"],
                   detail=f"Draft {rid} handed to {req['by']} for review; a person must send it and mark it sent")
        self.e.publish_record("A5", "report", rid, rep)

    def snapshot(self) -> dict:
        return {"reports": {k: v["status"] for k, v in self.reports.items()}}
