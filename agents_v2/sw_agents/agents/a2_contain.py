"""A2 containment: cut off a device at our own hub, mark the bed untrusted; one-click undo.

Triggers: TAMPERING, BOTH or DEVICE_ATTACK with confidence >= SW_A2_MIN_CONFIDENCE, or an
isolate_device / contain_incident request from a person. Broker control goes through
security_v2's Containment helper (mosquitto_ctrl dynsec disableClient/enableClient, argument
lists only, MON-01..12 validated, state confirmed). Without SW_DYNSEC_OPTIONS it is a dry run.
A2 never alerts nurses (A1 does; BOTH keeps the nurse alert) and never touches treatment.
After a person undoes a cut-off, A2 does not re-cut that device until the bed is NORMAL again.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from sw_common import bed_for_device, device_for_bed

from ..engine import Agent

log = logging.getLogger("sw_agents.a2")
DEVICE_RE = re.compile(r"MON-\d\d", re.ASCII)
TRIGGERS = frozenset({"TAMPERING", "BOTH", "DEVICE_ATTACK"})


def valid_device(device_id) -> str:
    if not isinstance(device_id, str) or not DEVICE_RE.fullmatch(device_id) or not 1 <= int(device_id[4:]) <= 12:
        raise ValueError("device must be MON-01..MON-12")
    return device_id


class DryRunBroker:
    mode = "dry_run"

    def disable(self, device: str) -> None:
        valid_device(device)

    def enable(self, device: str) -> None:
        valid_device(device)


class HubBroker:
    """security_v2 Containment. clean_session (disable + wipe saved session) when monitor creds exist."""

    mode = "hub"

    def __init__(self, options: str, audit: str, credentials: str | None = None) -> None:
        from sw_sec.containment import Containment  # security_v2, installed on the server
        self.helper = Containment(options, audit)
        self.credentials = credentials

    def disable(self, device: str) -> None:
        valid_device(device)
        if self.credentials:
            from sw_sec.io import private_read
            password = json.loads(private_read(self.credentials)).get(device)
            if password:
                self.helper.clean_session(device, password)
                return
        self.helper.disable_client(device)

    def enable(self, device: str) -> None:
        self.helper.enable_client(valid_device(device))


def make_broker(settings):
    if settings.a2_dry_run:
        return DryRunBroker()
    try:
        return HubBroker(settings.dynsec_options, settings.contain_audit or str(Path(settings.state_dir) / "containment.jsonl"),
                         settings.monitor_credentials)
    except Exception as exc:
        log.error("A2: hub containment unavailable (%s); using dry run", type(exc).__name__)
        return DryRunBroker()


class A2Contain(Agent):
    id = "A2"

    def __init__(self, engine, broker=None) -> None:
        super().__init__(engine)
        self.broker = broker or make_broker(engine.s)
        self.path = Path(engine.s.state_dir) / "a2_containment.json"
        self.contained: dict[str, dict] = {}
        self.released_by_person: set[str] = set()
        self._load()

    # ------------------------------------------------------------------ persistence
    def _load(self) -> None:
        """Containments survive a restart, so IT can still undo them."""
        try:
            data = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return
        for dev, c in (data or {}).items():
            try:
                valid_device(dev)
            except ValueError:
                continue
            self.contained[dev] = c
            for aid in (c.get("set_id"), c.get("disable_id")):
                if aid:
                    self.e.undo[aid] = ("A2", self._undo)
                    self.e.actions.setdefault(aid, {"action_id": aid, "device_id": dev})

    def _save(self) -> None:
        try:
            tmp = self.path.with_suffix(".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as fh:
                json.dump(self.contained, fh)
            os.replace(tmp, self.path)
        except OSError as exc:
            log.warning("A2 state save failed: %s", type(exc).__name__)

    def undoable_ids(self) -> set[str]:
        return {i for c in self.contained.values() for i in (c.get("set_id"), c.get("disable_id")) if i}

    def state_text(self, device: str) -> str:
        c = self.contained.get(device)
        if c is None:
            return "Device not cut off."
        when = self.e.hms(c["since"])
        if c.get("disable_result") == "dry_run":
            return f"DRY RUN: device would be cut off ({when}); bed marked untrusted."
        if c.get("disable_result") == "ok":
            return f"Device cut off {when}; bed marked untrusted."
        if c.get("disable_result") == "failed":
            return f"Cut-off FAILED at the hub ({when}); bed marked untrusted."
        return f"Cutting off device ({when}); bed marked untrusted."

    # ------------------------------------------------------------------ contain
    def contain(self, bed_id: str, why: str, approved_by: str | None = None) -> bool:
        device = valid_device(device_for_bed(bed_id))
        if device in self.contained:
            return False
        now = self.e.now()
        set_act = self.e.act("A2", "set_bed_untrusted", bed_id=bed_id, device_id=device, approved_by=approved_by,
                             detail=f"Bed {bed_id} marked UNTRUSTED ({why}); last trusted values stay on screen",
                             undo=self._undo)
        if set_act is None:
            return False
        c = {"bed_id": bed_id, "since": now, "set_id": set_act["action_id"], "disable_id": None,
             "disable_result": "pending", "why": why, "releasing": False}
        self.contained[device] = c
        self._save()

        def work() -> None:
            try:
                self.broker.disable(device)
                result = getattr(self.broker, "mode", "hub") == "dry_run" and "dry_run" or "ok"
            except Exception as exc:
                log.error("A2 disable %s failed: %s", device, type(exc).__name__)
                result = "failed"
            with self.e.lock:
                if self.contained.get(device) is not c:
                    return  # released or reset meanwhile
                detail = {"ok": f"Cut off {device} at the hub after {why}; session wiped",
                          "dry_run": f"DRY RUN: would cut off {device} after {why} (no hub control configured)",
                          "failed": f"Cut-off of {device} FAILED at the hub after {why}; bed stays untrusted"}[result]
                act = self.e.act("A2", "disable_client", bed_id=bed_id, device_id=device, detail=detail,
                                 approved_by=approved_by, result=result,
                                 undo=self._undo if result != "failed" else None)
                c["disable_result"] = result
                c["disable_id"] = act["action_id"] if act else None
                self._save()
                self.e.emit("containment", {"bed_id": bed_id, "device_id": device, "result": result,
                                            "text": self.state_text(device), "action": act})

        self.e.background(work)
        return True

    def _undo(self, original: dict, by: str | None) -> bool:
        device = original.get("device_id")
        c = self.contained.get(device) if device else None
        if c is None:
            c = next((x for x in self.contained.values() if original.get("action_id") in (x["set_id"], x["disable_id"])), None)
            device = device_for_bed(c["bed_id"]) if c else None
        if c is None or c.get("releasing"):
            return False
        self.release(device, by, original["action_id"], f"undo by {by}" if by else "undo")
        return True

    def release(self, device: str, by: str | None, undoes: str | None, why: str) -> None:
        c = self.contained[device]
        c["releasing"] = True
        bed = c["bed_id"]

        def work() -> None:
            was_cut = c.get("disable_result") in ("ok", "pending")
            try:
                if was_cut:
                    self.broker.enable(device)
                result = "dry_run" if c.get("disable_result") == "dry_run" or getattr(self.broker, "mode", "") == "dry_run" else "ok"
            except Exception as exc:
                log.error("A2 enable %s failed: %s", device, type(exc).__name__)
                result = "failed"
            with self.e.lock:
                target = undoes or c.get("disable_id") or c["set_id"]
                if result == "ok" and not was_cut:
                    detail = f"Bed {bed} trusted again ({why}); {device} had not been cut off at the hub"
                else:
                    detail = None
                detail = detail or (f"Re-enabled {device} at the hub ({why}); bed {bed} trusted again" if result == "ok" else
                          f"DRY RUN: would re-enable {device} ({why}); bed {bed} trusted again" if result == "dry_run" else
                          f"Re-enable of {device} FAILED at the hub ({why}); still cut off, try again")
                act = self.e.act("A2", "enable_client", bed_id=bed, device_id=device, detail=detail,
                                 undoes=target, approved_by=by, result=result)
                if result == "failed":
                    c["releasing"] = False
                    self._save()
                    return
                if act:
                    self.e.mark_undone([target], act["action_id"])
                    # The pair (set_bed_untrusted, disable_client) is undone together. Log the second undo
                    # explicitly so the action log / screens show both as undone (one hub change only).
                    for other in (c["set_id"], c.get("disable_id")):
                        if other and other != target and other not in self.e.undone:
                            act2 = self.e.act("A2", "enable_client", bed_id=bed, device_id=device, undoes=other,
                                              approved_by=by, result=result,
                                              detail=f"{other} undone together with {target} (same release, no second hub change)")
                            self.e.mark_undone([other], act2["action_id"] if act2 else act["action_id"])
                self.contained.pop(device, None)
                if by is not None:
                    self.released_by_person.add(device)
                self._save()
                self.e.emit("containment", {"bed_id": bed, "device_id": device, "result": "released",
                                            "text": self.state_text(device), "action": act})

        self.e.background(work)

    # ------------------------------------------------------------------ inputs
    def on_verdict(self, v: dict) -> None:
        bed, verdict = v["bed_id"], v["verdict"]
        device = device_for_bed(bed)
        if verdict == "NORMAL":
            self.released_by_person.discard(device)
            return
        if verdict not in TRIGGERS or v["confidence"] < self.e.s.a2_min_confidence or device in self.contained:
            return
        if device in self.released_by_person:
            return  # a person released it in this episode; don't override them
        self.contain(bed, f"{verdict} (conf {v['confidence']:.2f})")

    def isolate_request(self, req: dict) -> None:
        try:
            device = valid_device(req["target_id"])
        except ValueError:
            return self.e.refuse(req, "target is not MON-01..MON-12")
        if req.get("bed_id") and req["bed_id"] != bed_for_device(device):
            return self.e.refuse(req, "bed and device do not belong together")
        if device in self.contained:
            return self.e.refuse(req, "device already cut off")
        self.released_by_person.discard(device)
        self.contain(bed_for_device(device), f"isolate request by {req['by']}", approved_by=req["by"])

    def reset(self) -> None:
        self.released_by_person = set()
        if not self.e.s.a2_reset_releases:
            return
        for device, c in list(self.contained.items()):
            if not c.get("releasing"):
                self.release(device, None, c.get("disable_id") or c["set_id"], "demo reset")

    def snapshot(self) -> dict:
        return {"mode": getattr(self.broker, "mode", "?"),
                "contained": {d: {k: c.get(k) for k in ("bed_id", "since", "disable_result")} for d, c in self.contained.items()}}
