"""A4 fleet hunt: list the devices of one model, raise their watch level, report who to check next.

Inventory comes from SW_DEVICE_MODELS (default: all twelve are 'demo-monitor'); no hardware or
firmware discovery is claimed. Watch levels are bookkeeping shown on the action log; they do not
reconfigure the brain. A4 never cuts off a device itself (IT decides).
"""
from __future__ import annotations

from sw_common import bed_for_device

from ..engine import Agent, clean_text


class A4Fleet(Agent):
    id = "A4"

    def __init__(self, engine) -> None:
        super().__init__(engine)
        self.reset()

    def reset(self) -> None:
        self.watch: dict[str, dict] = {}  # set_watch_level action_id -> {devices, until, model}

    def _findings(self, devices: list[str]) -> list[str]:
        a2 = self.e.agents.get("A2")
        out = []
        for dev in devices:
            v = self.e.latest_verdict.get(bed_for_device(dev))
            contained = a2 is not None and dev in a2.contained
            if contained:
                out.append(f"{dev} (cut off)")
            elif v is None:
                out.append(f"{dev} (no verdict yet)")
            elif v["verdict"] != "NORMAL" or v["trust"] < 0.8:
                out.append(f"{dev} ({v['verdict']}, trust {v['trust']:.2f})")
        return out

    def hunt(self, model: str, approved_by: str | None, exclude: str | None = None, why: str = "") -> dict | None:
        inventory = self.e.s.device_models
        model = clean_text(model, 40)
        if model.lower() == "all":
            devices = sorted(inventory)
        else:
            devices = sorted(d for d, m in inventory.items() if m.lower() == model.lower())
        devices = [d for d in devices if d != exclude]
        if not devices:
            self.e.act("A4", "list_devices", approved_by=approved_by, result="no_devices",
                       detail=f"Fleet hunt{why}: no other devices of model '{model}' in the inventory")
            return None
        flagged = self._findings(devices)
        listing = f"{devices[0]}..{devices[-1]}" if len(devices) > 4 else ", ".join(devices)
        self.e.act("A4", "list_devices", approved_by=approved_by,
                   detail=f"Fleet hunt{why}: model '{model}': {len(devices)} devices ({listing}). Check next: "
                          + (", ".join(flagged) if flagged else "none flagged (all NORMAL and trusted)"))
        until = self.e.now() + int(self.e.s.watch_minutes * 60_000)
        act = self.e.act("A4", "set_watch_level", approved_by=approved_by, undo=self._undo,
                         detail=f"Watch level HIGH for {len(devices)} '{model}' devices until {self.e.hm(until)} "
                                f"(bookkeeping; IT decides any cut-off)")
        if act:
            aid = act["action_id"]
            self.watch[aid] = {"devices": devices, "until": until, "model": model}
            self.e.call_at(f"watch:{aid}", until, lambda: self._expire(aid))
        return act

    def _expire(self, aid: str) -> None:
        w = self.watch.pop(aid, None)
        if w is None:
            return
        self.e.undo.pop(aid, None)
        self.e.act("A4", "set_watch_level", detail=f"Watch level back to normal for {len(w['devices'])} '{w['model']}' devices (expired)")

    def _undo(self, original: dict, by: str | None) -> bool:
        aid = original["action_id"]
        w = self.watch.pop(aid, None)
        if w is None:
            return False
        self.e.cancel(f"watch:{aid}")
        act = self.e.act("A4", "set_watch_level", undoes=aid, approved_by=by,
                         detail=f"Watch level back to normal for {len(w['devices'])} '{w['model']}' devices (undo by {by})")
        if act:
            self.e.mark_undone([aid], act["action_id"])
        return True

    def hunt_request(self, req: dict) -> None:
        self.hunt(req["target_id"], req["by"])

    def on_event(self, name: str, data: dict) -> None:
        # R11: after A2 cuts a device off, hunt its model (automatic, logged, undoable)
        if name == "containment" and data.get("result") in ("ok", "dry_run") and self.e.s.a4_after_cutoff:
            dev = data["device_id"]
            model = self.e.s.device_models.get(dev)
            if model:
                self.hunt(model, None, exclude=dev, why=f" after {dev} was cut off")

    def snapshot(self) -> dict:
        return {"watch": {k: {"devices": len(v["devices"]), "until": v["until"]} for k, v in self.watch.items()}}
