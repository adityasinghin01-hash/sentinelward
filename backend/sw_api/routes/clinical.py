"""Bed detail, history and the bedside workflows (manual reading, nurse call, assignment), alerts."""
from __future__ import annotations

from fastapi import Body, Depends, FastAPI, HTTPException, Query

from sw_common import ALERT_STATUSES

from .. import commands, presenters
from ..models import (Acknowledge, Assign, AssignmentStatus, BedDetail, CallNurse, HistoryResponse, ManualReading,
                      Receipt)
from ..state import BUFFER_S
from . import Deps

CLINICAL = ("nurse", "doctor")


def register(app: FastAPI, d: Deps) -> None:
    """Add the clinical routes."""
    runtime = d.runtime

    @app.get("/api/beds/{bed_id}", response_model=BedDetail, tags=["ward"])
    async def bed_detail(bed_id: str, identity=Depends(d.user)):
        """One bed as on the ward screen, plus latest score per model, last 10 verdicts, device, open alerts."""
        d.require_bed(bed_id)
        await runtime.resolve_pins_now()
        return presenters.bed_detail(runtime.state, bed_id)

    @app.get("/api/beds/{bed_id}/history", response_model=HistoryResponse, tags=["ward"])
    async def history(bed_id: str, minutes: int = Query(default=30, ge=1, le=1440), identity=Depends(d.user)):
        """Per-second scalar history (no waveforms), oldest first. The newest 30 minutes come from RAM."""
        d.require_bed(bed_id)
        since = runtime.clock.ms() - minutes * 60_000
        points = runtime.state.history(bed_id, since)
        start = runtime.state.buffer_start(bed_id)
        if minutes * 60 > BUFFER_S:
            older = await runtime.store.history(bed_id, since)
            if start is not None:
                older = [p for p in older if p["ts"] < start]
            points = older + points
        return {"bed_id": bed_id, "points": points}

    @app.post("/api/beds/{bed_id}/manual-reading", status_code=201, response_model=Receipt,
              response_model_exclude_none=True, tags=["bedside"])
    async def manual_reading(bed_id: str, body: ManualReading, identity=Depends(d.roles(*CLINICAL))):
        """Record values taken by hand. Shown separately on the bed (manual), never merged into monitor values."""
        d.require_bed(bed_id)
        commands.agree(body.bedId, bed_id, "bedId")
        values = {"hr": body.hr if body.hr is not None else body.heartRate, "spo2": body.spo2, "sys": body.sys,
                  "dia": body.dia, "rr": body.rr}
        return commands.manual_reading(runtime, identity, bed_id, values, body.notes)

    @app.post("/api/beds/{bed_id}/call-nurse", status_code=201, response_model=Receipt,
              response_model_exclude_none=True, tags=["bedside"])
    async def call_nurse(bed_id: str, body: CallNurse = Body(default_factory=CallNurse),
                         identity=Depends(d.roles(*CLINICAL))):
        """Ask for a nurse at the bed. Stored and pushed on /ws; this API does not send Telegram messages."""
        d.require_bed(bed_id)
        commands.agree(body.bedId, bed_id, "bedId")
        now = runtime.clock.ms()
        previous = runtime.state.beds[bed_id].nurse_call
        if previous is not None and previous.get("status") == "open":
            runtime.store.save_nurse_call({**previous, "status": "replaced", "closed_ts": now,
                                           "closed_by": identity.staff_id})
        call = {"call_id": commands.identifier("call"), "bed_id": bed_id, "ts": now, "by": identity.staff_id,
                "note": body.notes, "urgency": body.urgency, "status": "open", "channel": "screen"}
        runtime.store.save_nurse_call(call)
        runtime.state.set_nurse_call(bed_id, call)
        runtime.push_bed(bed_id)
        return commands.receipt(runtime, command_id=call["call_id"])

    @app.post("/api/beds/{bed_id}/assignment", status_code=201, response_model=Receipt,
              response_model_exclude_none=True, tags=["bedside"])
    async def assign(bed_id: str, body: Assign, identity=Depends(d.roles(*CLINICAL))):
        """Assign a clinician to the bed. staff_id is set only when clinicianId names a configured user."""
        d.require_bed(bed_id)
        commands.agree(body.bedId, bed_id, "bedId")
        user = runtime.sessions.users.get(body.clinicianId.removeprefix("staff:"))
        staff_id = user.staff_id if user is not None and user.role in CLINICAL else None
        row = {"bed_id": bed_id, "ts": runtime.clock.ms(), "clinician_id": body.clinicianId,
               "staff_id": staff_id, "status": "assigned", "by": identity.staff_id}
        return _assignment(runtime, row)

    @app.post("/api/beds/{bed_id}/assignment/status", response_model=Receipt, response_model_exclude_none=True,
              tags=["bedside"])
    async def assignment_status(bed_id: str, body: AssignmentStatus, identity=Depends(d.roles(*CLINICAL))):
        """Move the bed's current assignment to assigned, on_my_way, reviewing or complete (audited)."""
        d.require_bed(bed_id)
        commands.agree(body.bedId, bed_id, "bedId")
        current = runtime.state.beds[bed_id].assignment
        if current is None:
            raise HTTPException(409, "Bed has no assignment")
        row = {"bed_id": bed_id, "ts": runtime.clock.ms(), "clinician_id": current["clinician_id"],
               "staff_id": current["staff_id"], "status": body.status, "by": identity.staff_id}
        return _assignment(runtime, row)

    @app.get("/api/alerts", response_model=list[dict], tags=["alerts"])
    async def alerts(status: str | None = Query(default=None), identity=Depends(d.user)):
        """Latest state of each alert (one entry per alert_id), newest first."""
        if status is not None and status not in ALERT_STATUSES:
            raise HTTPException(422, f"status must be one of {', '.join(ALERT_STATUSES)}")
        return runtime.state.alerts_list(status)

    @app.post("/api/alerts/{alert_id}/ack", status_code=202, response_model=Receipt,
              response_model_exclude_none=True, tags=["alerts"])
    async def ack(alert_id: str, body: Acknowledge = Body(default_factory=Acknowledge),
                  identity=Depends(d.roles(*CLINICAL))):
        """Ask A1 to acknowledge this alert (ward/request ack_alert)."""
        alert = runtime.state.alerts.get(alert_id)
        if alert is None:
            raise HTTPException(404, "Alert not found")
        if alert["status"] not in ("open", "escalated"):
            raise HTTPException(409, "Alert is no longer open")
        commands.agree(body.bedId, alert["bed_id"], "bedId")
        return commands.request(runtime, identity, "ack_alert", alert_id, alert["bed_id"], body.notes)


def _assignment(runtime, row: dict) -> dict:
    runtime.store.save_assignment(row)
    runtime.state.set_assignment(row["bed_id"], {k: row[k] for k in ("clinician_id", "staff_id", "status", "ts", "by")})
    runtime.push_bed(row["bed_id"])
    return commands.receipt(runtime)
