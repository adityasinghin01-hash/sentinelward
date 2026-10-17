"""Backend-only MQTT extension for display-only AI-chip second opinions.

The common Bus deliberately rejects unknown message shapes. This adapter keeps its
connection, subscriptions and reconnect behavior, routing only ward/chip messages
past that decoder to the backend's strict validator. No common contract is changed.
"""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sw_common import Bus
from sw_common.topics import topic_matches

CHIP_SUB = "ward/chip/+"
CHIP_TTL_MS = 120_000


class ChipOpinion(BaseModel):
    """Wire payload, also used verbatim in HTTP and WebSocket projections."""

    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)
    v: int = Field(ge=1, le=1)
    bed_id: str = Field(pattern=r"^B(?:0[1-9]|1[0-2])$")
    ts: int = Field(ge=0)
    alarm_code: Literal["ASYSTOLE", "BRADY", "TACHY", "VTACH", "VFIB"]
    p_real: float = Field(ge=0, le=1)
    label: Literal["real", "false"]
    threshold: float = Field(ge=0, le=1)
    model: str = Field(min_length=1, max_length=200)
    device: str = Field(min_length=1, max_length=200)
    latency_ms: float = Field(ge=0)
    heldout_challenge_cinc: float = Field(ge=0, le=1)
    heldout_challenge_vtac: float = Field(ge=0, le=1)


class ChipBus(Bus):
    """Use the common decoder everywhere except the separately validated chip topic."""

    def _on_message(self, client, userdata, msg) -> None:
        if not msg.topic.startswith("ward/chip/"):
            return super()._on_message(client, userdata, msg)
        with self._lock:
            self._stats["received"] += 1
            handlers = [h for p, h in self._handlers if topic_matches(p, msg.topic)]
        try:
            # A retained result must never reappear as a live second opinion.
            message = None if msg.retain else json.loads(msg.payload)
        except (ValueError, UnicodeError, RecursionError):
            message = None  # ingestion counts malformed JSON exactly once as invalid
        for handler in handlers:
            try:
                handler(message, msg.topic)
            except Exception:
                with self._lock:
                    self._stats["handler_errors"] += 1
                self._log.exception("chip handler raised on %s", msg.topic)
