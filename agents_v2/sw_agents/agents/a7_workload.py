"""A7 workload: alerts sent to each nurse in the last 2 h; warn the charge nurse at >= 40.

Counted from A1's real alerts (each alert counts once per person it reached). Publishes a
workload record every minute. Never reassigns anyone: the charge nurse decides.
"""
from __future__ import annotations

from collections import deque

from ..engine import Agent


class A7Workload(Agent):
    id = "A7"

    def __init__(self, engine) -> None:
        super().__init__(engine)
        self.record_id = engine.new_id("wl")
        self.reset()

    def reset(self) -> None:
        self.sent: dict[str, deque] = {}           # staff -> deque[(ts, alert_id)]
        self.seen: set[tuple[str, str]] = set()
        self.warned: dict[str, str] = {}           # staff -> warn action_id (active warning)

    def after_reset(self) -> None:
        self._schedule()

    def _schedule(self) -> None:
        self.e.call_at("a7:tick", self.e.now() + int(self.e.s.workload_every_s * 1000), self.tick)

    def on_event(self, name: str, data: dict) -> None:
        if name != "alert":
            return
        for staff in data["to"]:
            if (data["alert_id"], staff) not in self.seen:
                self.seen.add((data["alert_id"], staff))
                self.sent.setdefault(staff, deque()).append((data["ts"], data["alert_id"]))

    def counts(self) -> dict[str, int]:
        horizon = self.e.now() - int(self.e.s.workload_window_s * 1000)
        out = {n: 0 for n in self.e.s.nurses}
        for staff, q in self.sent.items():
            while q and q[0][0] < horizon:
                q.popleft()
            if staff in out or q:
                out[staff] = len(q)
        return out

    def tick(self) -> None:
        counts = self.counts()
        limit = self.e.s.workload_threshold
        nurses = [n for n in self.e.s.nurses]
        for staff, n in counts.items():
            if staff not in nurses:
                continue
            if n >= limit and staff not in self.warned:
                lightest = min((x for x in nurses if x != staff), key=lambda x: counts.get(x, 0), default=None)
                hint = f"; consider moving a bed to {lightest} ({counts.get(lightest, 0)} alarms)" if lightest else ""
                act = self.e.act("A7", "warn_workload", undo=self._undo,
                                 detail=f"To {self.e.s.charge_nurse}: {staff} received {n} alarms in the last "
                                        f"{int(self.e.s.workload_window_s // 3600)} h (limit {limit}){hint}. Charge nurse decides.")
                if act:
                    self.warned[staff] = act["action_id"]
            elif n < limit and staff in self.warned:
                aid = self.warned.pop(staff)
                self.e.undo.pop(aid, None)
        self.e.publish_record("A7", "workload", self.record_id, {
            "window_h": self.e.s.workload_window_s / 3600, "threshold": limit, "charge_nurse": self.e.s.charge_nurse,
            "nurses": [{"staff_id": s, "count": c, "over_limit": c >= limit} for s, c in sorted(counts.items())],
            "warnings": sorted(self.warned), "computed_ts": self.e.now()})
        self._schedule()

    def _undo(self, original: dict, by: str | None) -> bool:
        staff = next((s for s, a in self.warned.items() if a == original["action_id"]), None)
        if staff is None:
            return False
        act = self.e.act("A7", "warn_workload", undoes=original["action_id"], approved_by=by,
                         detail=f"Workload warning for {staff} withdrawn by {by}")
        if act:
            self.e.mark_undone([original["action_id"]], act["action_id"])
        # keep the staff entry so the same crossing does not re-warn at once
        self.warned[staff] = "withdrawn"
        return True

    def snapshot(self) -> dict:
        return {"counts": self.counts(), "warned": dict(self.warned)}
