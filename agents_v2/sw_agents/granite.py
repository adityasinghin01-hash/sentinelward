"""IBM Granite writer (llama.cpp OpenAI-compatible server) with a fact check and a truthful template.

Granite only writes prose from the facts it is given; its output is never parsed for actions.
The base model in IBM's LinuxONE image is not instruction-tuned, so the prompt is a fixed outline
plus the facts, and the output is rejected (template used instead) when it is empty, too long,
or mentions any number, bed or device that is not in the facts.
"""
from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger("sw_agents.granite")
NUM_RE = re.compile(r"\d+(?:\.\d+)?")
BED_RE = re.compile(r"\b(?:bed\s*|B)(\d{1,2})\b", re.IGNORECASE)
DEV_RE = re.compile(r"\bMON-(\d\d)\b", re.IGNORECASE)
FORBIDDEN = re.compile(r"https?://|<[a-z/]|```", re.IGNORECASE)


def allowed_numbers(facts: Any) -> set[str]:
    out: set[str] = set()

    def walk(x: Any) -> None:
        if isinstance(x, bool) or x is None:
            return
        if isinstance(x, (int, float)):
            for form in (str(x), str(int(x)) if float(x).is_integer() else None, f"{float(x):.1f}", f"{float(x):.0f}"):
                if form:
                    out.add(form)
        elif isinstance(x, str):
            out.update(NUM_RE.findall(x))
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)

    walk(facts)
    return out


def check_output(text: str, facts: dict) -> str | None:
    """None if the text is acceptable, else the reason it was rejected."""
    if not isinstance(text, str) or len(text.strip()) < 20:
        return "empty or too short"
    if len(text) > 1200:
        return "too long"
    if FORBIDDEN.search(text):
        return "contains markup or a link"
    numbers = allowed_numbers(facts)
    beds = {str(int(b[1:])) for b in facts.get("beds_mentioned", [])}
    devices = {d[-2:] for d in facts.get("devices_mentioned", [])}
    numbers |= beds | devices | {b[1:] for b in facts.get("beds_mentioned", [])} | {str(int(d)) for d in devices}
    for m in BED_RE.finditer(text):
        if str(int(m.group(1))) not in beds:
            return f"mentions bed {m.group(1)} which is not in the facts"
    for m in DEV_RE.finditer(text):
        if m.group(1) not in devices:
            return f"mentions MON-{m.group(1)} which is not in the facts"
    for n in NUM_RE.findall(text):
        if n not in numbers and n.rstrip("0").rstrip(".") not in numbers:
            return f"adds the number {n} which is not in the facts"
    return None


def _num_eq(text_value: str, fact) -> bool:
    try:
        return fact is not None and abs(float(text_value) - float(fact)) < 0.051
    except (TypeError, ValueError):
        return False


def check_claims(text: str, facts: dict) -> str | None:
    """Counts the text states must be the counts in the facts (a number being *somewhere* is not enough)."""
    t = text.lower()
    counts = [(r"(\d+) incidents?\b", "incident_count", "incidents"),
              (r"(\d+) (?:open )?(?:biomed(?:ical)? )?tickets?\b", "open_ticket_count", "open tickets"),
              (r"(\d+) (?:\w+ ){0,2}alerts?\b", "alerts_sent", "alerts"),
              (r"acknowledged (?:all )?(?:of them, )?(\d+)\b", "alerts_acknowledged", "acknowledged alerts"),
              (r"(\d+) false alarms?\b", "false_alarms_silenced", "false alarms"),
              (r"(\d+) untrusted beds?\b", "untrusted_bed_count", "untrusted beds"),
              (r"median (?:of |time of |acknowledgement time of )?(\d+(?:\.\d+)?)", "median_ack_s", "median")]
    for pattern, key, label in counts:
        for m in re.finditer(pattern, t):
            if not _num_eq(m.group(1), facts.get(key)):
                return f"says {m.group(0)!r} but the facts have {facts.get(key)} {label}"
    nones = [(r"\bno (?:\w+ ){0,2}incidents?\b", "incident_count"), (r"\bno (?:open )?(?:biomed(?:ical)? )?tickets?\b", "open_ticket_count"),
             (r"\bno (?:\w+ ){0,1}alerts?\b", "alerts_sent"), (r"\bno false alarms?\b", "false_alarms_silenced"),
             (r"\bno (?:beds? (?:are|is|were) )?untrusted\b|\bno untrusted beds?\b", "untrusted_bed_count")]
    for pattern, key in nones:
        m = re.search(pattern, t)
        if m and facts.get(key):
            return f"says {m.group(0)!r} but the facts have {facts.get(key)}"
    if re.search(r"acknowledged all\b", t) and facts.get("alerts_acknowledged") != facts.get("alerts_sent"):
        return "says all alerts were acknowledged but they were not"
    blind = {str(int(b["bed_id"][1:])): b["minutes"] for b in facts.get("blind_time") or []}
    bed_list = r"((?:\b(?:b|bed\s*)\d{1,2}\b(?:\s*,\s*|\s+and\s+|\s+or\s+)?)+)"
    for m in re.finditer(bed_list + r"[^.;,]{0,30}?(\d+(?:\.\d+)?) min", t):
        for b in re.findall(r"(?:b|bed\s*)(\d{1,2})", m.group(1)):
            if not _num_eq(m.group(2), blind.get(str(int(b)))):
                return f"says {m.group(0)!r} but that is not bed {int(b)}'s blind time"
    untrusted = {str(int(b[1:])) for b in facts.get("untrusted_beds") or []}
    for m in re.finditer(r"((?:\b(?:b|bed\s*)\d{1,2}\b(?:,|\s|and|or)*)+)(?:is|are|was|were|remains?|stays?) (?:still )?untrusted", t):
        for b in re.findall(r"(?:b|bed\s*)(\d{1,2})", m.group(1)):
            if str(int(b)) not in untrusted:
                return f"says bed {int(b)} is untrusted but it is not"
    return None


def tidy(seed: str, completion: str, truncated: bool = False) -> str:
    """seed + Granite's continuation, cut at the end of the note, repeats and any unfinished sentence.

    truncated: Granite stopped at max_tokens, so its last sentence may be cut short even if it ends
    in a full stop (e.g. "a median of 15." from "15.0 s"); it is dropped.
    """
    text = str(completion)
    ended = "\n" in text.strip() or any(m in text for m in ("Facts", "Handover note", "Outline"))
    text = text.lstrip().split("\n")[0]
    for marker in ("Facts", "Handover note", "Outline"):
        text = text.split(marker)[0]
    sentences, seen = [], set()
    for sent in re.split(r"(?<=\.)\s+", " ".join((seed + " " + text.strip()).split())):
        key = sent.lower().strip()
        if not key.endswith(".") or key in seen:  # unfinished (token limit) or a loop: stop here
            break
        seen.add(key)
        sentences.append(sent)
    else:
        if truncated and not ended and len(sentences) > 1:
            sentences.pop()
    return " ".join(sentences[:8])


def repeats(text: str, n: int = 5) -> str | None:
    """A 5-word run said twice: the small base model is looping, not writing."""
    words = re.findall(r"[a-z0-9.]+", text.lower())
    seen = set()
    for i in range(len(words) - n + 1):
        gram = " ".join(words[i:i + n])
        if gram in seen:
            return gram
        seen.add(gram)
    return None


PROMPT_SKIP = ("since_ts", "now_ts", "beds_mentioned", "devices_mentioned")

# One fixed example note (made-up beds/devices that the fact check refuses if copied). Granite 350M
# is a base model: it follows a worked example far better than an instruction.
EXAMPLE = ("Facts since 08:00:\n- Incidents: 1 (B02 TAMPERING open)\n- Untrusted beds: B02\n"
           "- Open biomed tickets: 1 (MON-11 drift)\n- Blind time: B02 3.5 min\n"
           "- Alerts to staff: 6, acknowledged 4, median 22.0 s to acknowledge\n- False alarms silenced: 2\n"
           "Handover note: Since 08:00 the ward had 1 incident: suspected tampering on B02, still open, so B02 is "
           "untrusted. There is 1 open biomed ticket, a drift on MON-11. B02 was blind for 3.5 min. Staff got 6 alerts "
           "and acknowledged 4, with a median of 22.0 s. 2 false alarms were silenced.\n\n")


def fact_lines(f: dict) -> str:
    """The facts in the outline order (incidents, untrusted beds, tickets, blind time, alerts)."""
    inc = ", ".join(f"{i['bed_id']} {i['verdict']} {i['status']}" for i in f.get("incidents") or []) or "none"
    tk = ", ".join(f"{t.get('device_id') or 'unknown device'} {t['problem']}" for t in f.get("open_tickets") or []) or "none"
    bl = ", ".join(f"{b['bed_id']} {b['minutes']} min" for b in f.get("blind_time") or []) or "none"
    med = f", median {f['median_ack_s']} s to acknowledge" if f.get("median_ack_s") is not None else ""
    return (f"- Incidents: {f.get('incident_count', 0)} ({inc})\n"
            f"- Untrusted beds: {', '.join(f.get('untrusted_beds') or []) or 'none'}\n"
            f"- Open biomed tickets: {f.get('open_ticket_count', 0)} ({tk})\n- Blind time: {bl}\n"
            f"- Alerts to staff: {f.get('alerts_sent', 0)}, acknowledged {f.get('alerts_acknowledged', 0)}{med}\n"
            f"- False alarms silenced: {f.get('false_alarms_silenced', 0)}\n")


def seed_for(facts: dict) -> str:
    return f"Since {facts.get('shift_start', '08:00')} the ward had"


def build_prompt(facts: dict, outline: str) -> str:
    """Fixed header + one worked example + these facts (outline order) + the start of the note."""
    return ("Ward shift handover notes. Each note uses only its own facts, in plain sentences, no advice.\n\n"
            + EXAMPLE + f"Facts since {facts.get('shift_start', '08:00')}:\n" + fact_lines(facts)
            + "Handover note: " + seed_for(facts))


class GraniteWriter:
    name = "IBM Granite"

    def __init__(self, url: str | None, timeout_s: float = 120.0, http: Any = None, max_tokens: int = 120) -> None:
        self.url = url.rstrip("/") if url else None
        self.timeout_s = timeout_s
        self.max_tokens = max_tokens
        self.last_trimmed: str | None = None
        self._http = http

    def _client(self):
        if self._http is None:
            import httpx
            self._http = httpx.Client(timeout=self.timeout_s)
        return self._http

    def write(self, facts: dict, outline: str) -> tuple[str | None, str | None]:
        """(text, None) from Granite, or (None, reason) when the template must be used."""
        if not self.url:
            return None, "SW_GRANITE_URL not set"
        prompt = build_prompt(facts, outline)
        try:
            # Granite 350M base on LinuxONE CPU writes ~4 tokens/s: ask for a short note (max_tokens ~120)
            # and wait up to timeout_s. Callers run this in a background thread; nothing waits on it.
            # (deploy/granite's server ignores "stop", so tidy() cuts the note client-side.)
            response = self._client().post(self.url + "/v1/completions",
                                           json={"prompt": prompt, "max_tokens": self.max_tokens, "temperature": 0.1,
                                                 "stop": ["\n\n", "Facts", "Outline"]})
            data = response.json()
            text = data["choices"][0]["text"]
            truncated = data["choices"][0].get("finish_reason") == "length"
        except Exception as exc:
            log.info("granite unavailable: %s", type(exc).__name__)
            return None, f"Granite unavailable ({type(exc).__name__})"
        text = tidy(seed_for(facts), text, truncated)
        self.last_trimmed = None
        reason = self.problem(text, facts)
        if reason:
            # Keep the longest leading part that passes every check (at least 2 sentences): what is
            # dropped is a sentence that was wrong or looping, nothing false is kept.
            sentences = re.split(r"(?<=\.)\s+", text)
            for k in range(len(sentences) - 1, 1, -1):
                part = " ".join(sentences[:k])
                if self.problem(part, facts) is None:
                    self.last_trimmed = f"{len(sentences) - k} sentence(s) dropped: {reason}"
                    log.info("granite output trimmed: %s", self.last_trimmed)
                    return part, None
            log.info("granite output rejected: %s", reason)
            return None, f"Granite output rejected: {reason}"
        return text, None

    @staticmethod
    def problem(text: str, facts: dict) -> str | None:
        loop = repeats(text)
        return check_output(text, facts) or check_claims(text, facts) or (f"repeats itself ({loop!r})" if loop else None)
