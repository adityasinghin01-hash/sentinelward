"""Reports, tickets, briefing and workload (records from agents, plus audited staff edits)."""
from __future__ import annotations

import copy
from datetime import datetime, timezone

from fastapi import Body, Depends, FastAPI, HTTPException, Query

from .. import commands, presenters
from ..lookups import CLOSED_TICKET, record_of, report_bed, report_for
from ..models import (BriefingResponse, CreateTicket, MarkSent, Receipt, RecordOut, SaveReport, UpdateTicket,
                      WorkloadResponse)
from ..state import record_bed
from . import Deps

ALL_STAFF = ("nurse", "doctor", "it", "biomed", "admin")
REPORT_EDITORS = ("it", "admin")
TICKET_EDITORS = ("biomed", "admin")
# Fields of the screen's CertReportDraft that the server sets itself.
SENT = frozenset({"sent", "human_marked_sent"})
SERVER_REPORT_FIELDS = frozenset({"incidentId", "savedAt", "sentAt", "sentBy", "status", "sent_at", "sent_by",
                                  "saved_at", "saved_by"})


def parse_since(raw: str | None) -> int | None:
    """?since= as epoch ms or ISO 8601 (Z or offset; naive means UTC); None when absent."""
    if raw is None or raw.strip() == "":
        return None
    raw = raw.strip()
    if raw.lstrip("-").isdigit():
        return int(raw)
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(422, "since must be epoch milliseconds or an ISO 8601 time") from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def iso(ms: int) -> str:
    """Epoch ms as ISO 8601 UTC with Z."""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def register(app: FastAPI, d: Deps) -> None:
    """Add the record routes."""
    runtime = d.runtime
    state = runtime.state

    # ------------------------------------------------------------------ reports

    @app.get("/api/reports", response_model=list[RecordOut], tags=["reports"])
    async def reports(identity=Depends(d.user)):
        """Report records (from A5), newest first."""
        return [presenters.record(r) for r in state.records_of("report")]

    @app.get("/api/reports/{report_id}", response_model=RecordOut, tags=["reports"])
    async def report(report_id: str, identity=Depends(d.user)):
        """One report by record_id, or by its incident ID / bed ID."""
        return presenters.record(report_for(state, report_id))

    async def save(report_id: str, body: SaveReport, identity) -> dict:
        rep = report_for(state, report_id)
        if body.incidentId is not None and body.incidentId not in (report_id, rep["data"].get("incident_id"),
                                                                     rep["record_id"]):
            raise HTTPException(422, "incidentId does not match the report")
        if rep["data"].get("status") in SENT:
            raise HTTPException(409, "Report was already marked sent")
        fields = {k: copy.deepcopy(v) for k, v in (body.report or body.data or {}).items()
                  if k not in SERVER_REPORT_FIELDS}
        if not fields:
            raise HTTPException(422, "No editable fields")
        fields["saved_at"], fields["saved_by"] = runtime.clock.ms(), identity.staff_id
        commands.edit_record(runtime, identity, rep["record_id"], fields)
        bed = report_bed(state, rep)
        if bed in state.beds:
            runtime.push_bed(bed)
        return commands.receipt(runtime)

    @app.patch("/api/reports/{report_id}", response_model=Receipt, response_model_exclude_none=True, tags=["reports"])
    async def patch_report(report_id: str, body: SaveReport, identity=Depends(d.roles(*REPORT_EDITORS))):
        """Save draft fields into data (one audit row per changed field). An agent republishing the
        report later replaces these edits; the audit rows stay."""
        return await save(report_id, body, identity)

    @app.post("/api/reports/{report_id}", response_model=Receipt, response_model_exclude_none=True,
              tags=["reports"])
    async def post_report(report_id: str, body: SaveReport, identity=Depends(d.roles(*REPORT_EDITORS))):
        """Same as PATCH /api/reports/<id>."""
        return await save(report_id, body, identity)

    @app.post("/api/reports/{report_id}/mark-sent", response_model=Receipt, response_model_exclude_none=True,
              tags=["reports"])
    async def mark_sent(report_id: str, body: MarkSent = Body(default_factory=MarkSent),
                        identity=Depends(d.roles(*REPORT_EDITORS))):
        """Record that a person sent the report outside SentinelWard: data.status = "sent" (audited) and a
        mark_report_sent action. Nothing is sent to any authority by this API."""
        rep = report_for(state, report_id)
        if rep["data"].get("status") in SENT:
            raise HTTPException(409, "Report was already marked sent")
        now = runtime.clock.ms()
        bed = report_bed(state, rep)
        commands.staff_action(runtime, identity, "mark_report_sent", bed, f"Report {rep['record_id']} marked sent")
        commands.edit_record(runtime, identity, rep["record_id"],
                             {"status": "sent", "sent_at": now, "sent_by": identity.staff_id})
        if bed in state.beds:
            runtime.push_bed(bed)
        return commands.receipt(runtime)

    # ------------------------------------------------------------------ tickets

    @app.get("/api/tickets", response_model=list[RecordOut], tags=["tickets"])
    async def tickets(status: str | None = Query(default=None), identity=Depends(d.user)):
        """Ticket records (A6 and staff), newest first; ?status= filters on data.status."""
        return [presenters.record(r) for r in state.records_of("ticket")
                if status is None or r["data"].get("status") == status]

    @app.post("/api/tickets", status_code=201, response_model=Receipt, response_model_exclude_none=True,
              tags=["tickets"])
    async def create_ticket(body: CreateTicket, identity=Depends(d.roles(*ALL_STAFF))):
        """Create a biomedical ticket (kind ticket, by staff:<name>), stored and pushed on /ws."""
        d.require_bed(body.bedId)
        now = runtime.clock.ms()
        rid = commands.identifier("tk_staff")
        rec = {"record_id": rid, "kind": "ticket", "ts": now, "by": identity.staff_id, "version": 1,
               "data": {"bed_id": body.bedId, "device_id": state.beds[body.bedId].cfg.device_id,
                        "issue": body.issue, "status": "open", "note": body.notes, "created_at": now,
                        "created_by": identity.staff_id, "source": "staff"},
               "updated_ts": None, "updated_by": None}
        state.put_record(rec)
        runtime.store.save_record(rec, [])
        runtime.push_bed(body.bedId)
        return commands.receipt(runtime, command_id=rid)

    @app.patch("/api/tickets/{ticket_id}", response_model=Receipt, response_model_exclude_none=True,
               tags=["tickets"])
    async def update_ticket(ticket_id: str, body: UpdateTicket, identity=Depends(d.roles(*TICKET_EDITORS))):
        """Change a ticket's status and/or note (one audit row per changed field)."""
        commands.agree(body.ticketId, ticket_id, "ticketId")
        rec = record_of(state, ticket_id, "ticket")
        changes = {}
        if body.status is not None:
            changes["status"] = body.status
        if body.note is not None:
            changes["note"] = body.note
        commands.edit_record(runtime, identity, rec["record_id"], changes)
        bed = record_bed(rec)
        if bed in state.beds:
            runtime.push_bed(bed)
        return commands.receipt(runtime)

    # ------------------------------------------------------------------ briefing and workload

    @app.get("/api/briefing", response_model=BriefingResponse, tags=["briefing"],
             responses={503: {"description": "No briefing record yet (A8 has not published one)"}})
    async def briefing(since: str | None = Query(default=None), identity=Depends(d.user)):
        """The newest A8 briefing at or after ?since= (ISO or epoch ms). summary and generated_by come from the
        record's narrative; the counts are computed by the backend from its stored data since that time."""
        cutoff = parse_since(since)
        rec = state.newest_record("briefing", cutoff)
        if rec is None:
            raise HTTPException(503, "No briefing has been published yet")
        data = rec["data"]
        narrative = data.get("narrative") if isinstance(data.get("narrative"), dict) else {}
        summary = narrative.get("text") if isinstance(narrative.get("text"), str) else data.get("summary")
        if not isinstance(summary, str):
            raise HTTPException(503, "The newest briefing has no summary text")
        generator = narrative.get("generator") or data.get("generated_by")
        start = cutoff if cutoff is not None else (data.get("since") if isinstance(data.get("since"), int) else rec["ts"])
        blind = await runtime.store.untrusted_seconds(start)
        return {
            "since": iso(start),
            "generated_by": "IBM Granite" if generator == "granite" else str(generator or "unknown"),
            "summary": summary,
            "incidents": sum(1 for r in state.records_of("incident") if r["ts"] >= start),
            "untrusted_beds": sum(1 for b in state.beds.values()
                                  if b.last_point is not None and not state.trusted_now(b)),
            "open_tickets": sum(1 for r in state.records_of("ticket") if r["data"].get("status") not in CLOSED_TICKET),
            "blind_time": [{"bed_id": b, "minutes": round(n / 60, 2)} for b, n in sorted(blind.items()) if n > 0],
            "record_id": rec["record_id"], "ts": rec["ts"],
        }

    @app.get("/api/workload", response_model=WorkloadResponse, response_model_exclude_none=True, tags=["briefing"])
    async def workload(hours: int = Query(default=2, ge=1, le=48), identity=Depends(d.user)):
        """Alarm load per nurse from the newest A7 workload record within ?hours=; {"nurses": []} when none."""
        rec = state.newest_record("workload", runtime.clock.ms() - hours * 3_600_000)
        if rec is None:
            return {"nurses": []}
        nurses = []
        for n in rec["data"].get("nurses") or []:
            if not isinstance(n, dict) or not isinstance(n.get("staff_id"), str) or type(n.get("count")) is not int:
                continue
            user = runtime.sessions.users.get(n["staff_id"].removeprefix("staff:"))
            nurses.append({"nurse_id": n["staff_id"], "nurse_name": user.display_name if user else n["staff_id"],
                           "alarms_last_2h": max(0, n["count"])})
        return {"nurses": nurses, "record_id": rec["record_id"], "ts": rec["ts"]}
