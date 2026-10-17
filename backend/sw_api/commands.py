"""Translate validated screen commands to sw_common publications."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4
from fastapi import HTTPException
from sw_common import make_action, make_bedside_check, make_demo_control, make_request, validate

from .config import UserConfig


def identifier(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def agree(supplied: str | None, actual: str | None, field: str) -> None:
    if supplied is not None and supplied != actual:
        raise HTTPException(422, f"{field} does not match the URL or stored relationship")


def receipt(runtime, command_id: str | None = None, **fields) -> dict:
    return {"command_id": command_id or identifier("cmd"), "accepted_at": runtime.clock.ms(), **fields}


def publish(runtime, messages: list[dict]) -> None:
    """Record every publication before trying the bus; retry only unsent siblings."""
    for message in messages:
        errors = validate(message)
        if errors:
            raise ValueError("Invalid outgoing contract: " + "; ".join(errors))
    for message in messages:
        runtime.store.save(message)
        runtime.store.enqueue(message)
    runtime.publish_pending()


def request(runtime, user: UserConfig, action: str, target_id: str, bed_id: str | None, note: str = "") -> dict:
    request_id = identifier("req")
    message = make_request(request_id=request_id, by=user.staff_id, action=action, target_id=target_id,
                           bed_id=bed_id, note=note, ts=runtime.clock.ms())
    publish(runtime, [message])
    return receipt(runtime, request_id=request_id)


def bedside(runtime, user: UserConfig, bed_id: str, result: str, notes: str) -> dict:
    check = make_bedside_check(bed_id=bed_id, result=result, by=user.staff_id, ts=runtime.clock.ms(), notes=notes)
    action = make_action(action_id=identifier("act"), by=user.staff_id, action="bedside_check", bed_id=bed_id,
                         device_id=runtime.state.beds[bed_id].cfg.device_id, detail=notes or result,
                         ts=runtime.clock.ms())
    publish(runtime, [check, action])
    runtime.state.on_bedside(check)
    runtime.state.on_action(action)
    runtime.push_bed(bed_id)
    return receipt(runtime)


def run_identifier(ms: int) -> str:
    """run_<YYYYMMDD_HHMMSS> in UTC, as doc 00 asks for demo_control."""
    return "run_" + datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y%m%d_%H%M%S")


def demo(runtime, cmd: str, scenario: str = "full_ward_script", speed: int = 1, start_at_s: int = 0) -> dict:
    run_id = run_identifier(runtime.clock.ms())
    message = make_demo_control(cmd=cmd, run_id=run_id, ts=runtime.clock.ms(), scenario=scenario, speed=speed, start_at_s=start_at_s)
    # A run starts a fresh ward, as the brain does: old verdicts, alerts and scores must not carry over.
    if cmd in ("reset", "run"):
        runtime.reset()
    publish(runtime, [message])
    return receipt(runtime, accepted=True, run_id=run_id)


def staff_action(runtime, user: UserConfig, action: str, bed_id: str | None, detail: str) -> dict:
    """Publish (via the outbox) and apply one staff action, e.g. manual_reading or mark_report_sent."""
    device_id = runtime.state.beds[bed_id].cfg.device_id if bed_id in runtime.state.beds else None
    message = make_action(action_id=identifier("act"), by=user.staff_id, action=action, bed_id=bed_id,
                          device_id=device_id, detail=detail[:240], ts=runtime.clock.ms())
    publish(runtime, [message])
    runtime.state.on_action(message)
    return message


def manual_reading(runtime, user: UserConfig, bed_id: str, values: dict, notes: str) -> dict:
    """Store a manual reading apart from monitor values, publish the manual_reading action."""
    ts = runtime.clock.ms()
    reading = {"reading_id": identifier("man"), "bed_id": bed_id, "ts": ts, "by": user.staff_id,
               **{k: values.get(k) for k in ("hr", "spo2", "sys", "dia", "rr")}, "notes": notes}
    runtime.store.save_manual(reading)
    runtime.state.add_manual(reading)
    shown = ", ".join(f"{k}={reading[k]:g}" for k in ("hr", "spo2", "sys", "dia", "rr") if reading[k] is not None)
    staff_action(runtime, user, "manual_reading", bed_id, f"Manual reading {shown}" + (f": {notes}" if notes else ""))
    runtime.push_bed(bed_id)
    return receipt(runtime, command_id=reading["reading_id"])


def edit_record(runtime, user: UserConfig, record_id: str, changes: dict) -> dict:
    """Apply audited staff edits to a record's data fields; returns the record."""
    rec, audits = runtime.state.patch_record(record_id, changes, user.staff_id)
    if audits:
        runtime.store.save_record(rec, audits)
    return rec
