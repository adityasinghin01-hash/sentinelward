"""Resolve the IDs the screens send to stored records, using only real stored relationships.

The screens address incidents by bed ID (/incidents/B07/contain) and reports by incident ID.
A bed resolves to its one unresolved incident; none is 404 and several are 409, never a guess.
"""
from __future__ import annotations

from fastapi import HTTPException

from .state import WardState, record_bed

CLOSED_INCIDENT = frozenset({"resolved", "closed"})
CLOSED_TICKET = frozenset({"resolved", "closed"})
SUPERSEDED_REPORT = frozenset({"superseded"})


def record_of(state: WardState, record_id: str, kind: str) -> dict:
    """The stored record with this ID and kind, else 404."""
    rec = state.records.get(record_id)
    if rec is None or rec["kind"] != kind:
        raise HTTPException(404, f"{kind.capitalize()} not found")
    return rec


def incident_for(state: WardState, ident: str) -> dict:
    """An incident by record_id, or the single unresolved incident of a bed ID."""
    rec = state.records.get(ident)
    if rec is not None and rec["kind"] == "incident":
        return rec
    if ident in state.beds:
        open_ = [r for r in state.records.values() if r["kind"] == "incident" and record_bed(r) == ident
                 and r["data"].get("status") not in CLOSED_INCIDENT]
        if not open_:
            raise HTTPException(404, f"No unresolved incident for bed {ident}")
        if len(open_) > 1:
            raise HTTPException(409, f"Bed {ident} has {len(open_)} unresolved incidents; use an incident ID")
        return open_[0]
    raise HTTPException(404, "Incident not found")


def report_for(state: WardState, ident: str) -> dict:
    """A report by record_id, or the single current report linked (data.incident_id) to an incident."""
    rec = state.records.get(ident)
    if rec is not None and rec["kind"] == "report":
        return rec
    incident = incident_for(state, ident)
    linked = [r for r in state.records.values() if r["kind"] == "report"
              and r["data"].get("incident_id") == incident["record_id"]
              and r["data"].get("status") not in SUPERSEDED_REPORT]
    if not linked:
        raise HTTPException(404, f"No report for incident {incident['record_id']}")
    if len(linked) > 1:
        raise HTTPException(409, f"Incident {incident['record_id']} has {len(linked)} current reports")
    return linked[0]


def report_bed(state: WardState, rec: dict) -> str | None:
    """The bed of a report: its own data.bed_id, else its incident's."""
    bed = record_bed(rec)
    if bed is not None:
        return bed
    incident = state.records.get(rec["data"].get("incident_id") or "")
    return record_bed(incident) if incident is not None else None
