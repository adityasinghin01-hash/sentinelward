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
    if cmd == "reset":
        runtime.reset()
    publish(runtime, [message])
    return receipt(runtime, accepted=True, run_id=run_id)
