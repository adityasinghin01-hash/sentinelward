"""A8 shift briefing: facts from real data since the shift start; IBM Granite writes the prose.

Facts come only from the agents' own state (verdicts, incidents, containments, tickets, alerts).
Free text from records, requests or Telegram is never given to Granite. If Granite is not set,
down, slow, or adds any number/bed/device not in the facts, a fixed template writes the text and
generated_by says so.

Granite 350M on the LinuxONE CPU needs ~30-60 s, so it runs on its own background thread (never
the hub-control worker) and nothing waits for it:
- every briefing is published at once (template, or a Granite text prepared earlier), then
  rewritten in place (same record_id) when Granite finishes with the current facts;
- for the ward script, Granite starts SW_A8_GRANITE_LEAD_S (60 s) before T+19:00, so the T+19:00
  briefing is already Granite's (facts as of that start, stated in facts_as_of), then refreshed.
A Granite text is always stored with the exact facts it was checked against.
"""
from __future__ import annotations

import statistics
import time

from ..clock import hm, iso, shift_start_ms
from ..engine import Agent
from ..granite import GraniteWriter

OUTLINE = ("1) incidents, 2) untrusted beds, 3) open biomed tickets, 4) blind time per bed, "
           "5) alerts and acknowledgements. Plain sentences, no advice.")
BLIND_GAP_CAP_MS = 15_000


class A8Briefing(Agent):
    id = "A8"

    def __init__(self, engine, writer: GraniteWriter | None = None, background=None) -> None:
        super().__init__(engine)
        self.writer = writer or GraniteWriter(engine.s.granite_url, engine.s.granite_timeout_s,
                                              max_tokens=engine.s.granite_max_tokens)
        self.background = background or engine.background  # A8's own thread in the service
        self.generation = 0
        self.busy = False  # one Granite call at a time; a new one is skipped, never queued
        self.stats = {"granite_ok": 0, "granite_fallback": 0, "granite_skipped_busy": 0, "last_granite_s": None}
        self.reset()

    def reset(self) -> None:
        self.generation += 1
        self.prepared: dict | None = None  # {"text", "facts", "ts"} from the early T+18:00 start
        self.preparing = False
        self.prepare_target: tuple[str, str] | None = None
        self.data_from: int | None = None
        self.blind_ms: dict[str, int] = {}
        self.last: dict[str, tuple[int, bool, str]] = {}
        self.silenced = 0
        self.latest: dict | None = None

    def after_reset(self) -> None:
        if self.e.s.briefing_every_s > 0:
            self.e.call_at("a8:periodic", self.e.now() + int(min(60, self.e.s.briefing_every_s) * 1000), self._periodic)

    def _periodic(self) -> None:
        self.generate("periodic")
        self.e.call_at("a8:periodic", self.e.now() + int(self.e.s.briefing_every_s * 1000), self._periodic)

    def on_run(self, msg: dict) -> None:
        info = self.e.run_info or {}
        speed = info.get("speed") or 1
        delay_s = (self.e.s.briefing_demo_at_s - info.get("start_at_s", 0)) / speed
        if delay_s > 0:
            self.e.call_at("a8:demo", self.e.now() + int(delay_s * 1000), lambda: self.generate("ward script T+19:00"))
            # Granite is slow on CPU: write the T+19:00 text early (T+18:00 by default) so it is on time.
            lead_s = min(delay_s, self.e.s.granite_lead_s)  # lead is wall-clock seconds (Granite's speed)
            if self.writer.url and lead_s > 0:
                self.e.call_at("a8:prepare", self.e.now() + int((delay_s - lead_s) * 1000), self.prepare)

    # ------------------------------------------------------------------ facts
    def _contained_beds(self) -> set[str]:
        a2 = self.e.agents.get("A2")
        return {c["bed_id"] for c in a2.contained.values()} if a2 else set()

    def on_verdict(self, v: dict) -> None:
        bed = v["bed_id"]
        if self.data_from is None:
            self.data_from = v["ts"]
        blind = v.get("last_trusted_ts") is not None or bed in self._contained_beds()
        prev = self.last.get(bed)
        if prev is not None and prev[1]:
            self.blind_ms[bed] = self.blind_ms.get(bed, 0) + max(0, min(v["ts"] - prev[0], BLIND_GAP_CAP_MS))
        if v["verdict"] == "LOOSE_SENSOR" and (prev is None or prev[2] != "LOOSE_SENSOR"):
            self.silenced += 1
        self.last[bed] = (v["ts"], blind, v["verdict"])

    def facts(self) -> dict:
        now = self.e.now()
        since = shift_start_ms(now, self.e.s.shift_start, self.e.tz)
        a1, a3, a6 = (self.e.agents.get(x) for x in ("A1", "A3", "A6"))
        incidents = [{"bed_id": i["bed_id"], "device_id": i["device_id"], "verdict": i["verdict"], "status": i["status"]}
                     for i in (a3.incidents.values() if a3 else []) if i["opened_ts"] >= since]
        untrusted = sorted(self._contained_beds() | {b for b, v in self.e.latest_verdict.items()
                                                     if v["verdict"] in ("TAMPERING", "BOTH")})
        tickets = [{"device_id": t["device_id"], "problem": t["problem"]} for t in (a6.open_tickets() if a6 else [])]
        tickets += [{"device_id": r["data"].get("device_id") if isinstance(r["data"].get("device_id"), str) else None,
                     "problem": "staff ticket"} for r in self.e.records.values()
                    if r["kind"] == "ticket" and r["by"] != "A6" and r["data"].get("status") in ("open", "assigned")]
        blind = [{"bed_id": b, "minutes": round(ms / 60000, 1)} for b, ms in sorted(self.blind_ms.items())
                 if round(ms / 60000, 1) > 0]  # under 3 s rounds to "0.0 min": not worth a line
        history = [h for h in (a1.history if a1 else []) if h["opened_ts"] >= since]
        acked = [h["acked_s"] for h in history if h["acked_s"] is not None]
        beds = sorted({x["bed_id"] for x in incidents + blind} | set(untrusted))
        devices = sorted({x["device_id"] for x in incidents + tickets if x.get("device_id")})
        return {
            "shift_start": self.e.s.shift_start, "since_ts": since, "now_ts": now,
            "data_from": hm(self.data_from, self.e.tz) if self.data_from else None,
            "incident_count": len(incidents), "incidents": incidents,
            "untrusted_bed_count": len(untrusted), "untrusted_beds": untrusted,
            "open_ticket_count": len(tickets), "open_tickets": tickets,
            "blind_time": blind,
            "alerts_sent": len(history), "alerts_acknowledged": len(acked),
            "median_ack_s": round(statistics.median(acked), 1) if acked else None,
            "false_alarms_silenced": self.silenced,
            "beds_mentioned": beds, "devices_mentioned": devices,
        }

    def template(self, f: dict) -> str:
        parts = [f"Shift briefing since {f['shift_start']}" + (f" (data from {f['data_from']})." if f["data_from"] else " (no ward data yet).")]
        if f["incidents"]:
            parts.append(f"Incidents: {f['incident_count']} (" + ", ".join(
                f"{i['bed_id']} {i['verdict']} {i['status']}" for i in f["incidents"]) + ").")
        else:
            parts.append("Incidents: none.")
        parts.append(f"Untrusted beds: {', '.join(f['untrusted_beds'])}." if f["untrusted_beds"] else "Untrusted beds: none.")
        if f["open_tickets"]:
            parts.append(f"Open biomed tickets: {f['open_ticket_count']} (" + ", ".join(
                f"{t['device_id'] or 'unknown device'} {t['problem']}" for t in f["open_tickets"]) + ").")
        else:
            parts.append("Open biomed tickets: none.")
        parts.append("Blind time: " + (", ".join(f"{b['bed_id']} {b['minutes']} min" for b in f["blind_time"]) or "none") + ".")
        ack = f", median {f['median_ack_s']} s to acknowledge" if f["median_ack_s"] is not None else ""
        parts.append(f"Alerts to staff: {f['alerts_sent']}, acknowledged {f['alerts_acknowledged']}{ack}. "
                     f"False alarms silenced: {f['false_alarms_silenced']}.")
        return " ".join(parts)

    # ------------------------------------------------------------------ write
    def _granite(self, facts: dict, done) -> bool:
        """Start one Granite call on A8's thread; done(text, why, seconds) runs under the engine lock."""
        if not self.writer.url:
            return False
        if self.busy:
            self.stats["granite_skipped_busy"] += 1
            return False
        self.busy = True
        gen = self.generation

        def work() -> None:
            t0 = time.monotonic()
            try:
                text, why = self.writer.write(facts, OUTLINE)  # network call, outside the lock
                if text and getattr(self.writer, "last_trimmed", None):
                    with self.e.lock:
                        self.e.note(agent="A8", msg=f"Granite text trimmed to its checked part: {self.writer.last_trimmed}")
            finally:
                secs = round(time.monotonic() - t0, 1)
            with self.e.lock:
                self.busy = False
                self.stats["last_granite_s"] = secs
                self.stats["granite_ok" if text else "granite_fallback"] += 1
                if gen != self.generation:
                    return  # a reset happened meanwhile
                done(text, why, secs)

        try:
            self.background(work)
        except Exception:
            self.busy = False
            raise
        return True

    def prepare(self) -> None:
        """Start Granite early for the T+19:00 briefing (facts as of now)."""
        facts = self.facts()
        self.prepared = None
        self.prepare_target = None

        def done(text, why, secs) -> None:
            target, self.prepare_target = self.prepare_target, None
            if not text:
                return self.e.note(agent="A8", msg=f"early Granite briefing not used: {why}")
            if target is not None:  # the briefing went out (template) while Granite was still writing
                self._publish(target[0], target[1], facts, text, None, "rewritten (started early)", secs)
            else:
                self.prepared = {"text": text, "facts": facts, "ts": facts["now_ts"], "secs": secs}

        self.preparing = self._granite(facts, done)

    def _publish(self, rid: str, trigger: str, facts: dict, text: str | None, why: str | None,
                 note: str, granite_s: float | None = None) -> bool:
        generator = GraniteWriter.name if text else "template"
        body = text or self.template(facts)
        data = {k: v for k, v in facts.items() if k not in ("beds_mentioned", "devices_mentioned", "now_ts")}
        data.update(since=iso(facts["since_ts"]), generated_ts=self.e.now(), trigger=trigger,
                    facts_as_of=hm(facts["now_ts"], self.e.tz),
                    untrusted_beds_count=facts["untrusted_bed_count"], generated_by=generator,
                    narrative={"text": body, "generator": generator, "fallback_reason": why,
                               "facts_checked": True, "granite_seconds": granite_s})
        if not self.e.publish_record("A8", "briefing", rid, data):
            return False
        self.latest = data
        self.e.act("A8", "write_briefing", detail=f"Briefing {rid} ({trigger}) {note} by {generator}"
                   + (f" in {granite_s} s" if text and granite_s is not None else "")
                   + (f"; template because: {why}" if why else ""))
        return True

    def generate(self, trigger: str) -> None:
        """Publish a briefing now (never waits for Granite), then let Granite rewrite it in place."""
        with self.e.lock:
            facts = self.facts()
            rid = self.e.new_id("br")
            pre, self.prepared = self.prepared, None
            fresh = pre is not None and facts["now_ts"] - pre["ts"] <= (self.e.s.granite_lead_s + 300) * 1000
            if fresh:
                self._publish(rid, trigger, pre["facts"], pre["text"], None, "written early", pre["secs"])
            elif not self.writer.url:
                self._publish(rid, trigger, facts, None, "SW_GRANITE_URL not set", "written")
                return
            elif self.busy:
                waiting = self.preparing and self.prepare_target is None and trigger != "periodic"
                self._publish(rid, trigger, facts, None, "Granite still writing (started early)" if waiting
                              else "Granite busy with an earlier briefing", "written")
                if waiting:
                    self.prepare_target = (rid, trigger)  # the early text will land in this record
                return
            else:
                self._publish(rid, trigger, facts, None, "Granite still writing", "written")

            def done(text, why, secs) -> None:
                if text:
                    self._publish(rid, trigger, facts, text, None, "refreshed", secs)
                elif not fresh:  # keep the template, now with Granite's real reason
                    self._publish(rid, trigger, facts, None, why, "kept", secs)
                else:
                    self.e.note(agent="A8", record_id=rid, msg=f"Granite refresh not used, early text kept: {why}")

            self.preparing = False
            self._granite(facts, done)

    def snapshot(self) -> dict:
        return {"latest_generated_by": (self.latest or {}).get("generated_by"), "granite_busy": self.busy, **self.stats}
