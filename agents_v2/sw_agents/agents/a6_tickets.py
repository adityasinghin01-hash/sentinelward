"""A6 biomed tickets: DRIFTING, or LOOSE_SENSOR episodes repeated on one device -> one ticket.

One open ticket per device and problem; repeats update it (never a duplicate). Tickets go to
biomedical engineering, not IT. A biomed engineer closes them on the screen.
"""
from __future__ import annotations

from collections import deque

from sw_common import device_for_bed

from ..engine import Agent

PROBLEMS = {
    "drift": ("Arterial line reading may be drifting away from the cuff",
              "Re-level and re-zero the transducer; take a cuff reading"),
    "loose_sensor": ("Sensor repeatedly loose (false alarms)",
                     "Check the lead/clip and cable; replace if worn"),
}


class A6Tickets(Agent):
    id = "A6"

    def __init__(self, engine) -> None:
        super().__init__(engine)
        self.reset()

    def reset(self) -> None:
        self.prev: dict[str, str] = {}
        self.loose: dict[str, deque] = {}
        self.open: dict[tuple[str, str], dict] = {}   # (device, problem) -> ticket data
        self.by_action: dict[str, tuple[str, str]] = {}

    def _publish(self, t: dict) -> None:
        self.e.publish_record("A6", "ticket", t["ticket_id"], dict(t, history=list(t["history"][-50:])))

    def _ticket(self, bed: str, problem: str, event: str, count: int | None = None) -> None:
        device = device_for_bed(bed)
        now = self.e.now()
        key = (device, problem)
        t = self.open.get(key)
        if t is None:
            issue, fix = PROBLEMS[problem]
            t = {"ticket_id": self.e.new_id("tk"), "bed_id": bed, "device_id": device, "problem": problem,
                 "issue": issue, "suggested_fix": fix, "team": "biomedical engineering", "status": "open",
                 "count": count or 1, "first_seen_ts": now, "last_seen_ts": now, "created_at": now,
                 "source": "A6", "history": [{"ts": now, "event": event}]}
            self.open[key] = t
            act = self.e.act("A6", "open_ticket", bed_id=bed, device_id=device, undo=self._undo,
                             detail=f"Biomed ticket {t['ticket_id']} for {device}: {issue}. Fix: {fix}")
            if act:
                self.by_action[act["action_id"]] = key
        else:
            t["count"] = count if count is not None else t["count"] + 1
            t["last_seen_ts"] = now
            t["history"].append({"ts": now, "event": event})
            self.e.act("A6", "update_ticket", bed_id=bed, device_id=device,
                       detail=f"Ticket {t['ticket_id']}: {event} (seen {t['count']} times)")
        self._publish(t)

    def on_verdict(self, v: dict) -> None:
        bed, verdict = v["bed_id"], v["verdict"]
        prev = self.prev.get(bed)
        self.prev[bed] = verdict
        if verdict == prev:
            return
        device = device_for_bed(bed)
        if verdict == "DRIFTING":
            self._ticket(bed, "drift", "DRIFTING verdict" + (" again" if (device, "drift") in self.open else ""))
        elif verdict == "LOOSE_SENSOR":
            now = self.e.now()
            q = self.loose.setdefault(device, deque())
            q.append(now)
            while q and q[0] < now - int(self.e.s.loose_window_s * 1000):
                q.popleft()
            if (device, "loose_sensor") in self.open:
                self._ticket(bed, "loose_sensor", "LOOSE_SENSOR again")
            elif len(q) >= self.e.s.loose_repeats:
                self._ticket(bed, "loose_sensor", f"LOOSE_SENSOR {len(q)} times in "
                             f"{int(self.e.s.loose_window_s // 60)} min", count=len(q))
        elif prev == "DRIFTING" and verdict == "NORMAL" and (device, "drift") in self.open:
            t = self.open[(device, "drift")]
            t["history"].append({"ts": self.e.now(), "event": "verdict back to NORMAL; ticket stays open for biomed"})
            self.e.act("A6", "update_ticket", bed_id=bed, device_id=device,
                       detail=f"Ticket {t['ticket_id']}: {device} back to NORMAL; stays open until biomed closes it")
            self._publish(t)

    def _undo(self, original: dict, by: str | None) -> bool:
        key = self.by_action.get(original["action_id"])
        t = self.open.pop(key, None) if key else None
        if t is None:
            return False
        t["status"] = "cancelled"
        t["history"].append({"ts": self.e.now(), "event": f"cancelled (undo by {by})"})
        act = self.e.act("A6", "update_ticket", bed_id=t["bed_id"], device_id=t["device_id"], undoes=original["action_id"],
                         approved_by=by, detail=f"Ticket {t['ticket_id']} cancelled (undo by {by})")
        if act:
            self.e.mark_undone([original["action_id"]], act["action_id"])
        self._publish(t)
        return True

    def open_tickets(self) -> list[dict]:
        return list(self.open.values())

    def snapshot(self) -> dict:
        return {"open": [t["ticket_id"] for t in self.open.values()]}
