"""A1 alerts and escalation ladder.

doc00 table: EMERGENCY/BOTH high, TAMPERING/UNSURE/DRIFTING medium, LOOSE_SENSOR low,
DEVICE_ATTACK none (IT only), NORMAL nobody. One alert per bed episode; changes edit it.
Ladder: step 1 assigned nurse, step 2 next nurse, step 3 all nurses + doctor, ladder_step_s each.
Rule 2: a lower-priority verdict (e.g. TAMPERING) never lowers or closes a high alert.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from html import escape

from sw_common import VERDICT_PRIORITY, device_for_bed, make_alert, make_bedside_check

from ..engine import Agent, bed_no, clean_text

ALERTING = frozenset({"EMERGENCY", "BOTH", "TAMPERING", "UNSURE", "DRIFTING", "LOOSE_SENSOR"})
IT_VERDICTS = frozenset({"TAMPERING", "BOTH", "DEVICE_ATTACK"})
RANK = {"none": 0, "low": 1, "medium": 2, "high": 3}
OPEN = ("open", "escalated")
ICON = {"EMERGENCY": "🔴", "BOTH": "🔴", "TAMPERING": "⚪", "UNSURE": "🟡", "DRIFTING": "🟡", "LOOSE_SENSOR": "🔵"}


def person(staff: str | None) -> str:
    if not staff:
        return "someone"
    name = staff.removeprefix("staff:")
    if name.startswith("dr_"):
        return "Dr " + name[3:].replace("_", " ").title()
    return name.replace("_", " ").title()


def is_learning(v: dict) -> bool:
    """Brain warm-up: UNSURE, not offline, and no eligible check is even mildly suspicious."""
    if v["verdict"] != "UNSURE":
        return False
    if any("offline" in str(r).lower() for r in v.get("reasons") or []):
        return False
    scores = [s for s in (v.get("scores") or {}).values() if isinstance(s, (int, float))]
    return all(s < 0.5 for s in scores)


def headline(verdict: str, bed_id: str, reasons: list[str], source: str) -> str:
    n = bed_no(bed_id)
    if source == "bedside":
        return f"Bed {n} — nurse reports patient NOT OK. Go now."
    if verdict == "EMERGENCY":
        heart = any(w in " ".join(reasons).lower() for w in ("alarm", "heart", "ecg", "rhythm", "vt", "vf"))
        return f"Bed {n} — possible {'heart ' if heart else ''}emergency. Go now."
    if verdict == "BOTH":
        return f"Bed {n} — GO NOW. Do not trust the screen numbers."
    if verdict == "TAMPERING":
        return f"Bed {n} — monitor can't be trusted."
    if verdict == "UNSURE":
        return f"Bed {n} — readings unclear."
    if verdict == "DRIFTING":
        return f"Bed {n} — blood pressure may be drifting."
    text = " ".join(reasons).lower()
    what = "finger sensor" if any(w in text for w in ("ppg", "pleth", "finger", "spo2")) else (
        "ECG lead" if "ecg" in text else "sensor")
    return f"Bed {n} — {what} loose."


ACTION_LINE = {
    "EMERGENCY": "",
    "BOTH": "Possible emergency on a monitor that may be tampered with.",
    "TAMPERING": "Check pulse and breathing by hand. Use a portable monitor.",
    "UNSURE": "Please check by hand.",
    "DRIFTING": "Re-level and re-zero the line; take a cuff reading.",
    "LOOSE_SENSOR": "False alarm silenced. Please refit the sensor.",
}


def buttons(verdict: str, alert_id: str, bed_id: str) -> list[list[tuple[str, str]]]:
    if verdict in ("EMERGENCY", "BOTH"):
        return [[("On my way", f"ack:{alert_id}"), ("Escalate", f"esc:{alert_id}")]]
    if verdict in ("TAMPERING", "UNSURE"):
        return [[("Patient OK", f"ok:{bed_id}:{alert_id}"), ("Patient NOT OK", f"nok:{bed_id}:{alert_id}")]]
    return [[("Done", f"ack:{alert_id}")]]


@dataclass
class Alert:
    alert_id: str
    bed_id: str
    verdict: str
    priority: str
    source: str
    reasons: list[str]
    to: list[str]
    opened_ts: int
    step_ts: int
    ladder_step: int = 1
    status: str = "open"
    acked_by: str | None = None
    acked_ts: int | None = None
    prev_status: str = "open"
    lines: list[str] = field(default_factory=list)  # extra lines (ack, escalation) shown on Telegram


class A1Alerts(Agent):
    id = "A1"

    def __init__(self, engine) -> None:
        super().__init__(engine)
        self.reset()

    def reset(self) -> None:
        self.current: dict[str, Alert] = {}
        self.by_id: dict[str, Alert] = {}
        self.ack_actions: dict[str, str] = {}
        self.streak: dict[str, int] = {}
        self.normal_streak: dict[str, int] = {}
        self.learning_noted: set[str] = set()
        self.it_open: dict[str, dict] = {}
        self.it_streak: dict[str, int] = {}
        self.unsure_closed: dict[str, tuple[int, frozenset]] = {}  # bed -> (close ts, nurses it had paged)
        self.repage_noted: set[str] = set()
        self.history: list[dict] = []  # for A8: {alert_id, bed_id, verdict, opened_ts, acked_s}

    # ------------------------------------------------------------------ text
    def plain(self, a: Alert) -> str:
        head = headline(a.verdict, a.bed_id, a.reasons, a.source)
        tail = ACTION_LINE.get(a.verdict, "") if a.source != "bedside" else ""
        return clean_text(f"{head} {tail}".strip(), 300)

    def html(self, a: Alert) -> str:
        head = headline(a.verdict, a.bed_id, a.reasons, a.source)
        parts = [f"{ICON.get(a.verdict, '🔴')} <b>{escape(head)}</b>"]
        if a.source != "bedside" and ACTION_LINE.get(a.verdict):
            parts.append(escape(ACTION_LINE[a.verdict]))
        if a.reasons:
            parts.append(escape(clean_text("; ".join(a.reasons[:2]), 240)))
        parts.append(self.e.hms(a.opened_ts))
        parts.extend(a.lines)
        return "\n".join(parts)

    # ------------------------------------------------------------------ people
    def recipients(self, bed_id: str, step: int) -> list[str]:
        s = self.e.s
        nurses = list(s.nurses)
        assigned = s.roster.get(bed_id, nurses[0])
        if step <= 1:
            return [assigned]
        if assigned in nurses and len(nurses) > 1:
            nxt = nurses[(nurses.index(assigned) + 1) % len(nurses)]
        else:
            nxt = next((n for n in nurses if n != assigned), s.doctor)
        if step == 2:
            return [assigned, nxt]
        out = [assigned]
        for p in nurses + [s.doctor]:
            if p not in out:
                out.append(p)
        return out

    def _telegram(self, a: Alert, staff: list[str], html: str, with_buttons: bool = True) -> str:
        tg = self.e.telegram
        if tg is None or not tg.enabled:
            return "telegram off"
        missing, queued = [], []
        for p in staff:
            chat = self.e.s.telegram_chats.get(p)
            if chat is None:
                missing.append(p)
                continue
            tg.upsert(a.alert_id, chat, html, buttons(a.verdict, a.alert_id, a.bed_id) if with_buttons else None)
            queued.append(p)
        if missing:
            return f"telegram queued for {', '.join(queued) or 'nobody'}; no chat for {', '.join(missing)}"
        return "telegram queued"

    def _publish(self, a: Alert) -> bool:
        msg = make_alert(alert_id=a.alert_id, ts=self.e.now(), bed_id=a.bed_id, verdict=a.verdict,
                         priority=a.priority, text=self.plain(a), to=list(a.to), ladder_step=a.ladder_step,
                         status=a.status, acked_by=a.acked_by, acked_ts=a.acked_ts)
        return self.e.publish_alert(msg)

    def _act(self, action: str, a: Alert, detail: str, channel: str = "", **kw):
        result = "screen_only" if channel.startswith("telegram off") else "ok"
        return self.e.act("A1", action, bed_id=a.bed_id, detail=f"{detail}; {channel}" if channel else detail,
                          result=kw.pop("result", result), **kw)

    def _schedule(self, a: Alert) -> None:
        key = f"ladder:{a.alert_id}"
        self.e.cancel(key)
        if a.status in OPEN and a.ladder_step < 3 and a.priority in self.e.s.ladder_priorities:
            due = a.step_ts + int(self.e.s.ladder_step_s * 1000)
            self.e.call_at(key, due, lambda aid=a.alert_id: self._step(aid, None))

    # ------------------------------------------------------------------ lifecycle
    def _open(self, bed_id: str, verdict: str, reasons: list[str], source: str) -> Alert:
        now = self.e.now()
        a = Alert(alert_id=self.e.new_id("al"), bed_id=bed_id, verdict=verdict, priority=VERDICT_PRIORITY[verdict],
                  source=source, reasons=[clean_text(r, 120) for r in reasons[:3]], to=self.recipients(bed_id, 1),
                  opened_ts=now, step_ts=now)
        self.current[bed_id] = a
        self.by_id[a.alert_id] = a
        self.history.append({"alert_id": a.alert_id, "bed_id": bed_id, "verdict": verdict, "opened_ts": now, "acked_s": None})
        self._publish(a)
        channel = self._telegram(a, a.to, self.html(a))
        self._act("send_message", a, f"Alert {a.alert_id} ({verdict}, {a.priority}) step 1 -> {', '.join(a.to)}", channel)
        if channel.startswith("telegram off"):
            self.e.note(agent="A1", alert_id=a.alert_id, msg="telegram off: alert on ward/alert and screens only")
        self._schedule(a)
        return a

    def _update(self, a: Alert, verdict: str, reasons: list[str], source: str | None = None) -> None:
        old = a.verdict
        upgraded = RANK[VERDICT_PRIORITY[verdict]] > RANK[a.priority]
        a.verdict, a.priority = verdict, VERDICT_PRIORITY[verdict]
        a.reasons = [clean_text(r, 120) for r in reasons[:3]]
        if source:
            a.source = source
        self._publish(a)
        channel = self._telegram(a, a.to, self.html(a), with_buttons=a.status in OPEN)
        self._act("edit_message", a, f"Alert {a.alert_id} updated {old} -> {verdict} ({a.priority})", channel)
        if upgraded and a.status in OPEN:
            a.step_ts = self.e.now()
            self._schedule(a)

    def _close(self, a: Alert, why: str) -> None:
        a.status = "closed"
        self.e.cancel(f"ladder:{a.alert_id}")
        a.lines.append(f"☑️ Closed: {escape(why)} at {self.e.hms(self.e.now())}")
        self._publish(a)
        channel = self._telegram(a, a.to, self.html(a), with_buttons=False)
        self._act("edit_message", a, f"Alert {a.alert_id} closed: {why}", channel)
        if self.current.get(a.bed_id) is a:
            del self.current[a.bed_id]

    def _step(self, alert_id: str, by: str | None) -> bool:
        a = self.by_id.get(alert_id)
        if a is None or self.current.get(a.bed_id) is not a or a.status not in OPEN or a.ladder_step >= 3:
            return False
        before = list(a.to)
        a.ladder_step += 1
        a.to = self.recipients(a.bed_id, a.ladder_step)
        a.status = "escalated"
        a.step_ts = self.e.now()
        new = [p for p in a.to if p not in before]
        waited = int(self.e.s.ladder_step_s)
        a.lines.append(f"⏫ Escalated to step {a.ladder_step} at {self.e.hms(a.step_ts)}")
        self._publish(a)
        n = bed_no(a.bed_id)
        what = "emergency" if a.priority == "high" else "alert"
        esc_html = (f"🔴 <b>Bed {n} — {what}, not acknowledged for {waited} s.</b> Please go.\n" if by is None else
                    f"🔴 <b>Bed {n} — {what} escalated by {escape(person(by))}.</b> Please go.\n") + self.html(a)
        ch_new = self._telegram(a, new, esc_html)
        self._telegram(a, before, self.html(a))
        why = f"no acknowledgement for {waited} s" if by is None else f"escalated by {by}"
        self._act("escalate", a, f"Alert {a.alert_id}: {why}; step {a.ladder_step} -> {', '.join(new) or 'same people'}",
                  ch_new, approved_by=by)
        self._schedule(a)
        return True

    def ack(self, alert_id: str, by: str, via: str) -> bool:
        a = self.by_id.get(alert_id)
        if a is None or a.status not in OPEN:
            return False
        now = self.e.now()
        a.prev_status, a.status, a.acked_by, a.acked_ts = a.status, "acked", by, now
        self.e.cancel(f"ladder:{a.alert_id}")
        secs = round((now - a.opened_ts) / 1000, 1)
        for h in self.history:
            if h["alert_id"] == a.alert_id:
                h["acked_s"] = secs
        a.lines.append(f"✅ Acknowledged by {escape(person(by))} at {self.e.hms(now)}")
        self._publish(a)
        channel = self._telegram(a, a.to, self.html(a), with_buttons=False)
        act = self._act("record_ack", a, f"Alert {a.alert_id} acknowledged by {by} via {via} after {secs} s "
                        f"(step {a.ladder_step})", channel, approved_by=by, undo=self._undo_ack)
        if act:
            self.ack_actions[act["action_id"]] = a.alert_id
        return True

    def _undo_ack(self, original: dict, by: str | None) -> bool:
        a = self.by_id.get(self.ack_actions.get(original["action_id"], ""))
        if a is None or a.status != "acked" or self.current.get(a.bed_id) is not a:
            return False
        a.status, a.acked_by, a.acked_ts, a.step_ts = a.prev_status, None, None, self.e.now()
        for h in self.history:
            if h["alert_id"] == a.alert_id:
                h["acked_s"] = None
        a.lines.append(f"↩️ Acknowledgement withdrawn by {escape(person(by))}; alert open again")
        self._publish(a)
        channel = self._telegram(a, a.to, self.html(a))
        act = self._act("record_ack", a, f"Acknowledgement of {a.alert_id} withdrawn by {by}; alert re-opened, "
                        f"ladder restarted", channel, undoes=original["action_id"], approved_by=by)
        if act:
            self.e.mark_undone([original["action_id"]], act["action_id"])
        self._schedule(a)
        return True

    # ------------------------------------------------------------------ inputs
    def _raise(self, bed_id: str, verdict: str, reasons: list[str], source: str, force_new: bool = False) -> None:
        pr = VERDICT_PRIORITY[verdict]
        a = self.current.get(bed_id)
        if a is None:
            self._open(bed_id, verdict, reasons, source)
        elif a.status == "acked" or force_new:
            if RANK[pr] > RANK[a.priority] or force_new:
                self._close(a, "superseded by a new alert")
                self._open(bed_id, verdict, reasons, source)
            elif RANK[pr] == RANK[a.priority] and verdict != a.verdict:
                self._update(a, verdict, reasons, source)
        elif RANK[pr] > RANK[a.priority] or (RANK[pr] == RANK[a.priority] and verdict != a.verdict):
            self._update(a, verdict, reasons, source)
        # lower priority: never lowers an open alert (safety rule 2)

    def on_verdict(self, v: dict) -> None:
        bed, verdict = v["bed_id"], v["verdict"]
        if verdict == "NORMAL":
            self.streak[bed] = 0
            self.it_streak[bed] = 0
            self.normal_streak[bed] = self.normal_streak.get(bed, 0) + 1
            self.learning_noted.discard(bed)
            if self.normal_streak[bed] >= self.e.s.clear_verdicts:
                self.it_open.pop(bed, None)
                a = self.current.get(bed)
                # UNSURE flaps: it closes only after SW_A1_UNSURE_CLEAR_VERDICTS (4) NORMALs in a row
                need = self.e.s.unsure_clear_verdicts if a is not None and a.verdict == "UNSURE" else self.e.s.clear_verdicts
                if a is not None and self.normal_streak[bed] >= need and (a.status == "acked" or a.priority != "high"):
                    if a.verdict == "UNSURE":
                        self.unsure_closed[bed] = (self.e.now(), frozenset(a.to))
                        self.repage_noted.discard(bed)
                    self._close(a, "bed back to NORMAL")
            return
        self.normal_streak[bed] = 0
        if verdict in IT_VERDICTS:
            self.it_streak[bed] = self.it_streak.get(bed, 0) + 1
            if (bed in self.it_open or v["confidence"] >= self.e.s.a2_min_confidence
                    or self.it_streak[bed] >= self.e.s.confirm_verdicts):
                self._it_notice(v)
        else:
            self.it_streak[bed] = 0
        if verdict == "DEVICE_ATTACK":
            return  # IT only: nurses are not alerted
        if is_learning(v):
            if bed not in self.learning_noted:
                self.learning_noted.add(bed)
                self.e.note(agent="A1", bed_id=bed, msg="brain warming up (UNSURE, no suspicious score): no nurse alert")
            return
        if verdict not in ALERTING:
            return
        self.streak[bed] = self.streak.get(bed, 0) + 1
        need = self.e.s.unsure_confirm_verdicts if verdict == "UNSURE" else self.e.s.confirm_verdicts
        if VERDICT_PRIORITY[verdict] != "high" and self.current.get(bed) is None and self.streak[bed] < need:
            return
        if verdict == "UNSURE" and self.current.get(bed) is None and self._unsure_cooldown(bed):
            return
        self._raise(bed, verdict, list(v.get("reasons") or []), "verdict")

    def _unsure_cooldown(self, bed: str) -> bool:
        """True while a new UNSURE page would reach the same nurse < SW_A1_UNSURE_REPAGE_S after the last closed."""
        last = self.unsure_closed.get(bed)
        if last is None:
            return False
        closed_ts, paged = last
        left_s = self.e.s.unsure_repage_s - (self.e.now() - closed_ts) / 1000
        if left_s <= 0 or not set(self.recipients(bed, 1)) <= paged:
            return False
        if bed not in self.repage_noted:
            self.repage_noted.add(bed)
            self.e.note(agent="A1", bed_id=bed, msg=f"UNSURE again {self.e.s.unsure_repage_s - left_s:.0f} s after the "
                        f"last UNSURE alert closed: no new page for {int(left_s)} s (bed screen shows UNSURE)")
        return True

    def on_bedside(self, b: dict) -> None:
        bed = b["bed_id"]
        a = self.current.get(bed)
        if b["result"] == "patient_not_ok":
            if a is not None and a.status in OPEN and a.priority == "high":
                if a.source != "bedside":
                    self._update(a, "EMERGENCY", ["Bedside nurse reports patient NOT OK"], "bedside")
                return
            self._raise(bed, "EMERGENCY", ["Bedside nurse reports patient NOT OK"], "bedside", force_new=a is not None)
        elif a is not None and a.status in OPEN:
            self.ack(a.alert_id, b["by"], "bedside check (patient OK)")

    def ack_request(self, req: dict) -> None:
        if not self.ack(req["target_id"], req["by"], "screen"):
            self.e.refuse(req, "no open alert with this ID")

    def escalate_request(self, req: dict) -> None:
        if not self._step(req["target_id"], req["by"]):
            self.e.refuse(req, "no open alert with this ID below step 3")

    def on_telegram(self, press: dict) -> None:
        """A button press, already parsed by telegram.parse_callback; the chat decides who pressed it."""
        staff = next((p for p, c in self.e.s.telegram_chats.items() if c == press.get("chat_id")), None)
        if staff is None:
            return self.e.note(agent="A1", msg="telegram button from an unknown chat ignored")
        kind = press["kind"]
        if kind == "ack":
            if not self.ack(press["alert_id"], staff, "telegram"):
                self.e.note(agent="A1", msg="telegram ack for a closed or unknown alert ignored", by=staff)
        elif kind == "esc":
            self._step(press["alert_id"], staff)
        elif kind in ("ok", "nok"):
            result = "patient_ok" if kind == "ok" else "patient_not_ok"
            check = make_bedside_check(bed_id=press["bed_id"], result=result, by=staff, ts=self.e.now())
            if self.e.publish(check):
                self.e.act(staff, "bedside_check", bed_id=press["bed_id"], detail=f"{result} via Telegram")
                self.e._handle(check)

    # ------------------------------------------------------------------ IT channel
    def _it_text(self, bed: str, info: dict) -> str:
        n = bed_no(bed)
        dev = device_for_bed(bed)
        label = {"TAMPERING": "tampering suspected", "BOTH": "tampering suspected during a possible emergency",
                 "DEVICE_ATTACK": "network attack suspected"}[info["verdict"]]
        a2 = self.e.agents.get("A2")
        contain = a2.state_text(dev) if a2 is not None else "containment agent not running"
        lines = [f"🛡 <b>{dev} (Bed {n}): {label}.</b>", escape(clean_text("; ".join(info["reasons"][:2]), 200)),
                 escape(contain), "Evidence, incident and CERT-In draft: Security screen. Report clock: 6 h.",
                 self.e.hms(info["ts"])]
        return "\n".join(x for x in lines if x)

    def _it_notice(self, v: dict) -> None:
        bed = v["bed_id"]
        info = self.it_open.get(bed)
        if info is not None and info["verdict"] == v["verdict"]:
            return
        new = info is None
        if new:
            info = {"key": self.e.new_id("it"), "ts": self.e.now()}
            self.it_open[bed] = info
        info.update(verdict=v["verdict"], reasons=[clean_text(r, 120) for r in (v.get("reasons") or [])[:3]])
        self._send_it(bed, "send_message" if new else "edit_message", f"IT notified: {device_for_bed(bed)} {v['verdict']}")

    def _send_it(self, bed: str, action: str, detail: str) -> None:
        info = self.it_open[bed]
        tg, chat = self.e.telegram, self.e.s.telegram_it_chat
        if tg is not None and tg.enabled and chat is not None:
            tg.upsert(info["key"], chat, self._it_text(bed, info))
            channel, result = "telegram IT group queued", "ok"
        else:
            channel, result = "telegram off or no IT chat: Security screen only", "screen_only"
        self.e.act("A1", action, bed_id=bed, device_id=device_for_bed(bed), detail=f"{detail}; {channel}", result=result)

    def on_event(self, name: str, data: dict) -> None:
        if name == "containment" and data.get("bed_id") in self.it_open:
            self._send_it(data["bed_id"], "edit_message", f"IT message updated: {data.get('text', '')}")

    def snapshot(self) -> dict:
        return {"open": {b: {"alert_id": a.alert_id, "verdict": a.verdict, "status": a.status, "step": a.ladder_step}
                         for b, a in self.current.items()}}
