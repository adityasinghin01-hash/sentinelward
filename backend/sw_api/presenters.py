"""Frontend HTTP/WS projections; conservative unknowns exist only here."""
from __future__ import annotations

from .state import FAILED_RESULTS, LIVE, OFFLINE, WardState


def vitals(latest: dict | None) -> dict | None:
    if latest is None:
        return None
    bp = latest.get("bp") or {}
    return {"hr": latest.get("hr"), "spo2": latest.get("spo2"), "systolic": bp.get("sys"), "diastolic": bp.get("dia")}


def waveform(state: WardState, bed_id: str, ts: int | None, *, trusted: bool = False) -> dict:
    wave = state.waveform(bed_id, ts, trusted=trusted) if ts is not None else {}
    return {channel: [x for x in wave.get(channel, []) if x is not None] for channel in ("ecg", "ppg")}


def bed(state: WardState, bed_id: str, preview: bool = False) -> dict:
    entry = state.beds[bed_id]
    view = state.view(bed_id)
    verdict = entry.verdict
    device = state.device_brief(entry.cfg.device_id)
    trusted = bool(verdict is not None and view.display == LIVE and view.latest_trusted and not device["isolated"])
    shown_ts = view.latest["ts"] if view.latest is not None else None
    snapshot = None
    if view.latest is not None and view.latest_trusted:
        snapshot = {"captured_at": shown_ts, "vitals": vitals(view.latest), "waveform": waveform(state, bed_id, shown_ts, trusted=bool(view.latest_trusted))}
    payload = {
        "bed_id": bed_id, "device_id": entry.cfg.device_id,
        "verdict": verdict["verdict"] if verdict else "UNSURE",
        "priority": verdict["priority"] if verdict else "medium",
        "trust_score": 100 * verdict["trust"] if verdict else 0,
        "is_trusted": trusted, "connected": view.display != OFFLINE,
        "isolated": device["isolated"],
        "reason": "; ".join(verdict["reasons"]) if verdict else "Awaiting verdict",
        "requested_action": "Check patient at bedside" if verdict and verdict["priority"] in ("high", "medium") else "Continue monitoring",
        "acknowledged": any(a["bed_id"] == bed_id and a["status"] == "acked" for a in state.alerts.values()) and not bool(state.open_alerts(bed_id)),
        "last_updated_at": entry.last_rx_ms,
        "vitals": vitals(view.latest), "waveform": waveform(state, bed_id, shown_ts, trusted=bool(view.latest_trusted)),
        "last_trusted": snapshot, "display": view.display, "offline_since": view.offline_since,
    }
    if not preview:
        payload.update(patient=entry.cfg.patient(), manual=entry.manual, last_bedside_check=entry.last_bedside)
    return payload


def ward(state: WardState, preview: bool = False) -> dict:
    ids = state.ward.preview_beds if preview else state.beds
    return {"beds": [bed(state, bed_id, preview) for bed_id in ids], "received_at": state.clock.ms()}


def undoable(action: dict, actions: list[dict]) -> bool:
    return bool(action.get("undo_id") and not action.get("undoes") and action.get("result") not in FAILED_RESULTS and not any(a.get("undoes") == action["action_id"] and a.get("result") not in FAILED_RESULTS for a in actions))


def action_log(actions: list[dict], limit: int) -> dict:
    ordered = sorted(actions, key=lambda a: a["ts"], reverse=True)[:limit]
    return {"actions": [{"id": a["action_id"], "occurred_at": a["ts"], "actor": a["by"],
                         "action_code": a["action"], "action": a.get("detail") or a["action"],
                         "bed_id": a.get("bed_id"), "device_id": a.get("device_id"), "approved_by": a.get("approved_by"),
                         "mode": "person" if a["by"].startswith("staff:") else "automatic", "undoable": undoable(a, actions),
                         "references_action_id": a.get("undoes")} for a in ordered]}
