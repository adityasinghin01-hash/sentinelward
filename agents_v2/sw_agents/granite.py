"""IBM Granite writer (llama.cpp OpenAI-compatible server) with a fact check and a truthful template.

Granite only writes prose from the facts it is given; its output is never parsed for actions.
The base model in IBM's LinuxONE image is not instruction-tuned, so the prompt is a fixed outline
plus the facts, and the output is rejected (template used instead) when it is empty, too long,
or mentions any number, bed or device that is not in the facts.
"""
from __future__ import annotations

import json
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


class GraniteWriter:
    name = "IBM Granite"

    def __init__(self, url: str | None, timeout_s: float = 20.0, http: Any = None) -> None:
        self.url = url.rstrip("/") if url else None
        self.timeout_s = timeout_s
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
        prompt = ("You write short, factual hospital shift handover notes. Use ONLY the facts below. "
                  "Do not add numbers, beds or devices that are not in the facts.\n"
                  f"Facts (JSON): {json.dumps(facts, sort_keys=True, separators=(',', ':'))}\n"
                  f"Outline: {outline}\nHandover note:")
        try:
            response = self._client().post(self.url + "/v1/completions",
                                           json={"prompt": prompt, "max_tokens": 220, "temperature": 0.1,
                                                 "stop": ["\n\n", "Facts", "Outline"]})
            data = response.json()
            text = data["choices"][0]["text"]
        except Exception as exc:
            log.info("granite unavailable: %s", type(exc).__name__)
            return None, f"Granite unavailable ({type(exc).__name__})"
        text = " ".join(str(text).split())
        reason = check_output(text, facts)
        if reason:
            log.info("granite output rejected: %s", reason)
            return None, f"Granite output rejected: {reason}"
        return text, None
