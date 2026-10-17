"""MQTT thread bridge: copy and schedule; memory and WS run on the asyncio loop."""
from __future__ import annotations

import asyncio
import copy
import logging
from typing import TYPE_CHECKING

from sw_common import ALL_SUB, parse_topic, validate

if TYPE_CHECKING:
    from .app import Runtime

LOG = logging.getLogger(__name__)


class Ingest:
    """Validate even injected buses, reject stale generations, update state immediately."""

    def __init__(self, runtime: Runtime):
        self.runtime = runtime
        self.loop: asyncio.AbstractEventLoop | None = None
        self.generation = 0
        self.reset_at: int | None = None
        self.invalid = 0
        self._logged: set[str] = set()
        self.accepting = True

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def start(self) -> None:
        self.bind(asyncio.get_running_loop())
        self.runtime.bus.subscribe(ALL_SUB, self.callback)
        self.runtime.bus.connect(wait_s=0)

    def callback(self, message: dict, topic: str) -> None:
        if self.loop is None or not self.accepting:
            return
        generation = self.generation
        copied = copy.deepcopy(message)
        try:
            self.loop.call_soon_threadsafe(self.process, copied, topic, generation)
        except RuntimeError:
            if not self.loop.is_closed():
                raise

    def reset(self) -> None:
        self.generation += 1
        self.reset_at = self.runtime.clock.ms()

    def process(self, message: dict, topic: str, generation: int | None = None) -> bool:
        if generation is not None and generation != self.generation:
            return False
        errors = validate(message)
        if not errors:
            try:
                parsed = parse_topic(topic)
                if parsed.kind != message["type"] or any(value is not None and value != message.get(key) for key, value in parsed._asdict().items() if key != "kind"):
                    errors = ["topic does not match payload"]
            except ValueError as exc:
                errors = [str(exc)]
        if errors:
            self.invalid += 1
            if topic not in self._logged and len(self._logged) < 10000:
                self._logged.add(topic)
                LOG.warning("invalid message on %s: %s", topic, "; ".join(errors[:5]))
            return False
        # Scores/features use the beginning of their aligned source window.
        source_ts = message.get("ts", message.get("window_start", 0))
        if self.reset_at is not None and source_ts <= self.reset_at:
            return False
        state, store = self.runtime.state, self.runtime.store
        bed_id, device_id = message.get("bed_id"), message.get("device_id")
        if bed_id is not None and bed_id not in state.beds:
            return False
        if device_id is not None and device_id not in state.devices:
            return False
        m = copy.deepcopy(message)
        kind = m["type"]
        marks, point, old_record, record = [], None, None, None
        affected = {bed_id} if bed_id else set()
        if device_id:
            affected.add(state.devices[device_id].bed_id)
        if kind == "vitals":
            point, _ = state.on_vitals(m)
        elif kind == "score":
            state.on_score(m)
        elif kind == "verdict":
            _, mark = state.on_verdict(m)
            marks = [mark] if mark else []
        elif kind == "action":
            _, marks = state.on_action(m)
            if m.get("undoes"):
                original = store.actions.get(m["undoes"]) or state.actions.get(m["undoes"], {})
                if original.get("bed_id"):
                    affected.add(original["bed_id"])
                elif original.get("device_id") in state.devices:
                    affected.add(state.devices[original["device_id"]].bed_id)
        elif kind == "alert":
            state.on_alert(m)
        elif kind == "bedside_check":
            state.on_bedside(m)
        elif kind == "net_features":
            state.on_net(m)
        elif kind == "record":
            old_record = copy.deepcopy(state.records.get(m["record_id"]))
            record = state.on_record(m)
            related = m["data"].get("bed_id")
            if related in state.beds:
                affected.add(related)
        else:
            return True  # Own request/control echoes must not re-run operations.
        store.save(m, point, marks, old_record, record)
        self.runtime.resolve_pins()
        state.last_message_ms = self.runtime.clock.ms()
        for affected_id in affected:
            self.runtime.push_bed(affected_id, critical=kind != "vitals")
        return True
