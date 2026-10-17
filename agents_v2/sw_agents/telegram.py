"""Telegram Bot API via httpx: one message per (alert, chat), edited in place, at most 1 send/s.

Without a token the client is 'off': nothing is sent, A1 logs 'telegram off' and alerts still go
to ward/alert and the screens. The token is part of the URL path, so URLs, httpx logs and
exception texts are never logged; only exception class names are.
Only callback buttons are read from Telegram (allowed_updates=callback_query); typed chat text is
never read, so it can't steer anything.
"""
from __future__ import annotations

import logging
import re
import threading
from collections import OrderedDict
from typing import Any, Callable

log = logging.getLogger("sw_agents.telegram")
for _noisy in ("httpx", "httpcore"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

CALLBACK_RE = re.compile(r"(ack|esc):(al_[a-z0-9]{1,24})|(ok|nok):(B\d\d):(al_[a-z0-9]{1,24})", re.ASCII)


class Telegram:
    def __init__(self, token: str | None, clock, *, min_interval_s: float = 1.0,
                 http: Any = None, on_result: Callable[[str, Any, bool], None] | None = None) -> None:
        self.enabled = bool(token)
        self.clock = clock
        self.min_interval_ms = int(min_interval_s * 1000)
        self._lock = threading.Lock()
        self.pending: OrderedDict[tuple[str, int], dict] = OrderedDict()
        self.message_ids: dict[tuple[str, int], int] = {}
        self.last_send_ms = -10**12
        self.offset = 0
        self.sent = 0
        self.failed = 0
        self.on_result = on_result
        self._http = http
        if self.enabled and http is None:
            import httpx
            self._http = httpx.Client(base_url=f"https://api.telegram.org/bot{token}/", timeout=15.0)

    # ---------------------------------------------------------------- queue
    def upsert(self, key: str, chat_id: int, html: str, buttons: list[list[tuple[str, str]]] | None = None) -> bool:
        """Queue a send (first time) or an edit (afterwards). Repeats for the same key merge."""
        if not self.enabled:
            return False
        with self._lock:
            self.pending[(key, chat_id)] = {"text": html[:4000], "buttons": buttons or []}
            self.pending.move_to_end((key, chat_id))
        return True

    def reset(self) -> None:
        with self._lock:
            self.pending.clear()
            self.message_ids.clear()

    def pump(self) -> bool:
        """Do at most one Bot API call if the 1 msg/s budget allows. Returns True if a call was made."""
        if not self.enabled:
            return False
        with self._lock:
            now = self.clock.now_ms()
            if not self.pending or now - self.last_send_ms < self.min_interval_ms:
                return False
            (key, chat_id), op = self.pending.popitem(last=False)
            message_id = self.message_ids.get((key, chat_id))
            self.last_send_ms = now
        body: dict[str, Any] = {"chat_id": chat_id, "text": op["text"], "parse_mode": "HTML"}
        if op["buttons"]:
            body["reply_markup"] = {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row]
                                                        for row in op["buttons"]]}
        method = "editMessageText" if message_id else "sendMessage"
        if message_id:
            body["message_id"] = message_id
        ok, result = self._call(method, body)
        with self._lock:
            if ok and method == "sendMessage" and isinstance(result, dict) and "message_id" in result:
                self.message_ids[(key, chat_id)] = int(result["message_id"])
            if ok:
                self.sent += 1
            else:
                self.failed += 1
        if self.on_result:
            self.on_result(key, chat_id, ok)
        return True

    def _call(self, method: str, body: dict, timeout_s: float | None = None) -> tuple[bool, Any]:
        try:
            response = self._http.post(method, json=body, **({"timeout": timeout_s} if timeout_s else {}))
            data = response.json()
        except Exception as exc:
            log.warning("telegram %s failed: %s", method, type(exc).__name__)
            return False, None
        if not isinstance(data, dict) or not data.get("ok"):
            # 'message is not modified' on an identical edit is harmless
            desc = str(data.get("description", "")) if isinstance(data, dict) else ""
            if "not modified" in desc:
                return True, None
            log.warning("telegram %s rejected (HTTP %s)", method, getattr(response, "status_code", "?"))
            return False, None
        return True, data.get("result")

    # ---------------------------------------------------------------- callbacks
    def poll(self, timeout_s: int = 20) -> list[dict]:
        """Long-poll getUpdates; return parsed button presses [{chat_id, kind, bed_id, alert_id}]."""
        if not self.enabled:
            return []
        # The HTTP read must outlast Telegram's long poll, or every quiet poll ends in ReadTimeout.
        ok, result = self._call("getUpdates", {"offset": self.offset, "timeout": timeout_s,
                                               "allowed_updates": ["callback_query"]}, timeout_s=timeout_s + 10)
        presses = []
        updates = result if ok and isinstance(result, list) else []
        for update in updates:
            if not isinstance(update, dict) or type(update.get("update_id")) is not int:
                continue
            self.offset = max(self.offset, update["update_id"] + 1)
            cq = update.get("callback_query")
            if not isinstance(cq, dict):
                continue
            parsed = parse_callback(cq.get("data"))
            chat = ((cq.get("message") or {}).get("chat") or {}).get("id")
            self._call("answerCallbackQuery", {"callback_query_id": str(cq.get("id", ""))[:64],
                                               "text": "Received" if parsed else "Unknown button"})
            if parsed and isinstance(chat, int):
                parsed["chat_id"] = chat
                presses.append(parsed)
        return presses

    def close(self) -> None:
        if self._http is not None and hasattr(self._http, "close"):
            self._http.close()


def parse_callback(data: Any) -> dict | None:
    if not isinstance(data, str) or len(data.encode()) > 64:
        return None
    m = CALLBACK_RE.fullmatch(data)
    if not m:
        return None
    if m.group(1):
        return {"kind": m.group(1), "alert_id": m.group(2), "bed_id": None}
    return {"kind": m.group(3), "bed_id": m.group(4), "alert_id": m.group(5)}
