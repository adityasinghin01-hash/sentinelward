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
    # No verdict yet is not a doubt about the patient: an empty bed or a monitor still filling its first window.
    empty = verdict is None and view.latest is None
    waiting = "No monitor connected yet" if empty else "Waiting for the first check (about 10 s)"
    payload = {
        "bed_id": bed_id, "device_id": entry.cfg.device_id,
        "verdict": verdict["verdict"] if verdict else None,
        "priority": verdict["priority"] if verdict else "none",
        "trust_score": 100 * verdict["trust"] if verdict else 0,
        "is_trusted": trusted, "connected": view.display != OFFLINE,
        "isolated": device["isolated"],
        "reason": "; ".join(verdict["reasons"]) if verdict else waiting,
        "requested_action": ("Check patient at bedside" if verdict["priority"] in ("high", "medium") else "Continue monitoring") if verdict else "None",
        "acknowledged": any(a["bed_id"] == bed_id and a["status"] == "acked" for a in state.alerts.values()) and not bool(state.open_alerts(bed_id)),
        "last_updated_at": entry.last_rx_ms,
        "vitals": vitals(view.latest), "waveform": waveform(state, bed_id, shown_ts, trusted=bool(view.latest_trusted)),
        "last_trusted": snapshot, "display": "empty" if empty else view.display, "offline_since": view.offline_since,
    }
    if not preview:
        payload.update(patient=entry.cfg.patient(), manual=entry.manual, last_bedside_check=entry.last_bedside,
                       assignment=entry.assignment, nurse_call=entry.nurse_call)
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


def bed_detail(state: WardState, bed_id: str) -> dict:
    """GET /api/beds/<id>: the bed payload plus scores, recent verdicts, device and open alerts."""
    entry = state.beds[bed_id]
    payload = bed(state, bed_id)
    payload.update(scores=dict(sorted(entry.scores.items())), recent_verdicts=list(entry.recent_verdicts),
                   device=state.device_brief(entry.cfg.device_id), open_alerts=state.open_alerts(bed_id),
                   monitor_alarm=dict(entry.alarm) if entry.alarm else None)
    return payload


def devices(state: WardState) -> list[dict]:
    """GET /api/devices: each device plus the newest known sender count from its buffered net_features rows."""
    out = []
    for item in state.devices_list():
        rows = state.devices[item["device_id"]].net_rows
        known = max((r for r in rows if isinstance(r.get("senders"), (int, float))),
                    key=lambda r: r["window_start"], default=None)
        item.update(senders=known["senders"] if known else None,
                    senders_window_start=known["window_start"] if known else None)
        out.append(item)
    return out


BRIEFING_FACTS = ("since_ts", "shift_start", "data_from", "incident_count", "incidents", "untrusted_bed_count",
                  "untrusted_beds", "open_ticket_count", "open_tickets", "blind_time", "alerts_sent",
                  "alerts_acknowledged", "median_ack_s", "false_alarms_silenced")


def briefing_facts(data: dict) -> dict | None:
    """The facts an A8 briefing record was written from (only keys the record has), or None."""
    facts = {k: data[k] for k in BRIEFING_FACTS if k in data}
    return facts or None


def record(rec: dict) -> dict:
    """A stored record as returned by the record endpoints."""
    return {k: rec.get(k) for k in ("record_id", "kind", "ts", "by", "version", "data", "updated_ts", "updated_by")}
