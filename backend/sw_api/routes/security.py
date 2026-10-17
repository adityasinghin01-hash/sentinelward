"""Device network history, fleet hunt and incident workflows (evidence, contain, resolve, report review)."""
from __future__ import annotations

import copy
import hashlib
import json

from fastapi import Body, Depends, FastAPI, HTTPException, Query

from .. import commands, presenters
from ..lookups import CLOSED_INCIDENT, incident_for, report_for
from ..models import FleetHunt, IncidentCommand, Receipt, RecordOut, ReviewReport
from ..state import NET_BUFFER, record_bed
from . import Deps

SECURITY = ("it", "admin")


def evidence_item(runtime, incident: dict, bed_id: str | None, by: str) -> dict:
    """A snapshot of data the backend actually holds, fingerprinted with SHA-256 over its canonical JSON."""
    state = runtime.state
    now = runtime.clock.ms()
    content: dict = {"incident_id": incident["record_id"], "captured_at": now, "captured_by": by, "bed": None,
                     "verdict": None, "scores": {}, "net_features": None, "actions": []}
    if bed_id in state.beds:
        bed = state.beds[bed_id]
        content.update(bed=presenters.bed(state, bed_id, preview=True), verdict=bed.verdict,
                       scores=dict(sorted(bed.scores.items())),
                       net_features=state.devices[bed.cfg.device_id].net,
                       actions=[a for a in state.actions_list(5000)
                                if a.get("bed_id") == bed_id or a.get("device_id") == bed.cfg.device_id][:50])
    blob = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    evidence_id = commands.identifier("ev")
    return {"evidence_id": evidence_id, "kind": "signal_snapshot", "label": f"Manual snapshot of {bed_id or 'ward'}",
            "captured_at": now, "captured_by": by, "source": "manual", "filename": f"{evidence_id}.json",
            "size_bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest(), "content": content}


def register(app: FastAPI, d: Deps) -> None:
    """Add the security routes."""
    runtime = d.runtime

    @app.get("/api/devices/{device_id}/network", response_model=list[dict], tags=["security"])
    async def network(device_id: str, minutes: int = Query(default=10, ge=1, le=1440), identity=Depends(d.user)):
        """Stored net_features messages (all fields), oldest first."""
        if device_id not in runtime.state.devices:
            raise HTTPException(404, "Device not found")
        since = runtime.clock.ms() - minutes * 60_000
        if minutes * 60 <= NET_BUFFER * 5:
            return runtime.state.net_rows(device_id, since)
        return await runtime.store.net_rows(device_id, since)

    @app.post("/api/fleet-hunt", status_code=202, response_model=Receipt, response_model_exclude_none=True,
              tags=["security"])
    async def fleet_hunt(body: FleetHunt = Body(default_factory=FleetHunt), identity=Depends(d.roles(*SECURITY))):
        """Ask A4 to check every monitor of a model ("all" for the whole fleet)."""
        return commands.request(runtime, identity, "fleet_hunt", body.model, None, body.notes)

    @app.get("/api/incidents", response_model=list[RecordOut], tags=["incidents"])
    async def incidents(identity=Depends(d.user)):
        """Incident records (from A3), newest first."""
        return [presenters.record(r) for r in runtime.state.records_of("incident")]

    @app.get("/api/incidents/{incident_id}", response_model=RecordOut, tags=["incidents"])
    async def incident(incident_id: str, identity=Depends(d.user)):
        """One incident by record_id, or the single unresolved incident of a bed ID."""
        return presenters.record(incident_for(runtime.state, incident_id))

    @app.get("/api/incidents/{incident_id}/evidence", response_model=list[dict], tags=["incidents"])
    async def evidence(incident_id: str, identity=Depends(d.user)):
        """The incident's data.evidence list, or []."""
        ev = incident_for(runtime.state, incident_id)["data"].get("evidence")
        return ev if isinstance(ev, list) else []

    @app.post("/api/incidents/{incident_id}/evidence", status_code=201, response_model=Receipt,
              response_model_exclude_none=True, tags=["incidents"])
    async def capture(incident_id: str, body: IncidentCommand = Body(default_factory=IncidentCommand),
                      identity=Depends(d.roles(*SECURITY))):
        """Append a fingerprinted snapshot of the stored bed data to data.evidence (audited)."""
        rec = _incident(runtime, incident_id, body)
        bed_id = record_bed(rec)
        item = evidence_item(runtime, rec, bed_id, identity.staff_id)
        old = rec["data"].get("evidence")
        commands.edit_record(runtime, identity, rec["record_id"],
                             {"evidence": (copy.deepcopy(old) if isinstance(old, list) else []) + [item]})
        if bed_id in runtime.state.beds:
            runtime.push_bed(bed_id)
        return commands.receipt(runtime, command_id=item["evidence_id"])

    @app.post("/api/incidents/{incident_id}/contain", status_code=202, response_model=Receipt,
              response_model_exclude_none=True, tags=["incidents"])
    async def contain(incident_id: str, body: IncidentCommand = Body(default_factory=IncidentCommand),
                      identity=Depends(d.roles(*SECURITY))):
        """Ask A3 to contain the incident (ward/request contain_incident)."""
        rec = _incident(runtime, incident_id, body)
        return commands.request(runtime, identity, "contain_incident", rec["record_id"], record_bed(rec),
                                body.notes or body.reason)

    @app.post("/api/incidents/{incident_id}/resolve", status_code=202, response_model=Receipt,
              response_model_exclude_none=True, tags=["incidents"])
    async def resolve(incident_id: str, body: IncidentCommand = Body(default_factory=IncidentCommand),
                      identity=Depends(d.roles(*SECURITY))):
        """Ask A3 to resolve the incident; the reason goes in the request note."""
        rec = _incident(runtime, incident_id, body)
        return commands.request(runtime, identity, "resolve_incident", rec["record_id"], record_bed(rec),
                                body.reason or body.notes)

    @app.post("/api/incidents/{incident_id}/report/review", status_code=202, response_model=Receipt,
              response_model_exclude_none=True, tags=["incidents"])
    async def review(incident_id: str, body: ReviewReport = Body(default_factory=ReviewReport),
                     identity=Depends(d.roles(*SECURITY))):
        """Ask A5 to review the incident's report (ward/request review_report, target = report record_id)."""
        commands.agree(body.incidentId, incident_id, "incidentId")
        rep = report_for(runtime.state, incident_id)
        bed = record_bed(rep) or record_bed(runtime.state.records.get(rep["data"].get("incident_id") or "", {}))
        return commands.request(runtime, identity, "review_report", rep["record_id"], bed, body.notes)


def _incident(runtime, ident: str, body: IncidentCommand) -> dict:
    rec = incident_for(runtime.state, ident)
    if body.incidentId not in (None, ident, rec["record_id"]):
        raise HTTPException(422, "incidentId does not match the URL or stored relationship")
    commands.agree(body.bedId, record_bed(rec), "bedId")
    if body.type in ("contain_incident", "resolve_incident") and rec["data"].get("status") in CLOSED_INCIDENT:
        raise HTTPException(409, "Incident is already resolved")
    return rec
