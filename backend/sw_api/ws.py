"""Event-loop-only WebSocket fan-out with bounded per-client queues.

The application calls ``flush`` from its periodic ticker. MQTT callbacks must
schedule ingestion on the event loop before touching this hub.
"""
from __future__ import annotations

import asyncio
from collections import deque
from copy import deepcopy
import time
from typing import Any


class Client:
    """One subscriber; ``get`` returns None when the connection must close."""

    def __init__(self) -> None:
        self.closed = False
        self._queue: deque[tuple[dict, bool]] = deque()
        self._available = asyncio.Event()

    @property
    def qsize(self) -> int:
        return len(self._queue)

    async def get(self) -> dict | None:
        while not self.closed:
            if self._queue:
                message, _critical = self._queue.popleft()
                if not self._queue:
                    self._available.clear()
                return message
            await self._available.wait()
        return None

    def _close(self) -> None:
        self.closed = True
        self._queue.clear()
        self._available.set()

    def _put(self, message: dict, critical: bool) -> None:
        if self.closed:
            return
        self._queue.append((deepcopy(message), critical))
        # A soft overflow sacrifices telemetry, never clinical/security events.
        if len(self._queue) > 500:
            excess = len(self._queue) - 500
            kept = deque()
            for entry in self._queue:
                if excess and not entry[1]:
                    excess -= 1
                else:
                    kept.append(entry)
            self._queue = kept
        if len(self._queue) > 2000:
            self._close()
        else:
            self._available.set()


class Hub:
    """Fan out frontend envelopes, keeping only the latest delayed telemetry."""

    def __init__(self, clock: Any = None) -> None:
        self._mono = clock.mono if clock is not None else time.monotonic
        self._clients: set[Client] = set()
        self._last_telemetry: dict[str, float] = {}
        self._pending: dict[str, dict] = {}

    def subscribe(self, initial: list[dict]) -> Client:
        client = Client()
        # No await: the full snapshot is enqueued before any live event can run.
        for bed in initial:
            client._put({"type": "bed.updated", "payload": bed}, True)
        self._clients.add(client)
        return client

    def unsubscribe(self, client: Client) -> None:
        self._clients.discard(client)
        client._close()

    def broadcast(self, message: dict, critical: bool = True) -> None:
        bed_id = self._bed_id(message)
        if critical or bed_id is None:
            if bed_id is not None:
                # Otherwise a pre-verdict sample could follow the verdict later.
                self._pending.pop(bed_id, None)
            self._send(message, True)
            return
        now = self._mono()
        if now - self._last_telemetry.get(bed_id, float("-inf")) >= 1.0:
            self._pending.pop(bed_id, None)
            self._last_telemetry[bed_id] = now
            self._send(message, False)
        else:
            self._pending[bed_id] = deepcopy(message)

    def flush(self) -> None:
        now = self._mono()
        for bed_id, message in list(self._pending.items()):
            if now - self._last_telemetry.get(bed_id, float("-inf")) >= 1.0:
                del self._pending[bed_id]
                self._last_telemetry[bed_id] = now
                self._send(message, False)

    def _send(self, message: dict, critical: bool) -> None:
        for client in tuple(self._clients):
            client._put(message, critical)
            if client.closed:
                self._clients.discard(client)

    @staticmethod
    def _bed_id(message: dict) -> str | None:
        if message.get("type") != "bed.updated":
            return None
        payload = message.get("payload")
        return payload.get("bed_id") if isinstance(payload, dict) else None
