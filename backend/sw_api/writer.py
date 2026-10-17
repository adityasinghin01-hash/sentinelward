"""One-second batch writer for PostgreSQL.

Writes are queued as (sql, params) on the event loop without waiting. A background task commits
everything queued so far in one transaction at most once per second, grouping consecutive rows
of the same statement into one pipelined executemany. A failed batch is rolled back and retried
in the same order (every statement is idempotent: upserts or ON CONFLICT DO NOTHING), so a
database outage delays rows but does not lose them. close() drains the queue before returning.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Any, Awaitable, Callable

LOG = logging.getLogger(__name__)

FLUSH_INTERVAL_S = 1.0
MAX_QUEUED = 2_000_000  # about a day of the whole ward; beyond this the oldest rows are dropped
DRAIN_ATTEMPTS = 5

Op = tuple[str, Any]


class BatchWriter:
    """Queue SQL operations and commit them in batches; see the module docstring."""

    def __init__(self, connect: Callable[[], Awaitable[Any]], interval_s: float = FLUSH_INTERVAL_S) -> None:
        self._connect = connect
        self.interval_s = interval_s
        self._queue: deque[Op] = deque()
        self._conn: Any = None
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self._lock = asyncio.Lock()
        self._closing = False
        self.ok = False
        self._epoch = 0
        self.dropped = 0
        self.batches = 0
        self.rows_written = 0
        self.last_error: str | None = None
        self.last_commit_mono: float | None = None

    @property
    def queued(self) -> int:
        """Operations waiting for the next commit."""
        return len(self._queue)

    def put(self, sql: str, params: Any) -> None:
        """Queue one statement execution (never blocks)."""
        self._queue.append((sql, params))
        if len(self._queue) > MAX_QUEUED:
            self._queue.popleft()
            self.dropped += 1
            if self.dropped == 1 or self.dropped % 10_000 == 0:
                LOG.error("database write queue full: %d oldest rows dropped", self.dropped)

    def discard(self, keep: Callable[[str], bool]) -> None:
        """Drop queued operations whose SQL does not satisfy keep (used by a demo reset)."""
        self._queue = deque(op for op in self._queue if keep(op[0]))
        self._epoch += 1

    def start(self) -> None:
        """Start the background flush task on the running loop."""
        self._task = asyncio.create_task(self._run(), name="sw-db-writer")

    async def _run(self) -> None:
        while not self._closing:
            try:
                await asyncio.wait_for(self._wake.wait(), self.interval_s)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
            if self._closing:
                break
            await self.flush()  # at most one commit per interval

    async def flush(self) -> bool:
        """Commit everything queued now; True on success (or nothing to do)."""
        async with self._lock:  # one transaction at a time on the single write connection
            return await self._flush()

    async def _flush(self) -> bool:
        if not self._queue:
            return True
        batch = list(self._queue)
        epoch = self._epoch
        try:
            if self._conn is None or self._conn.closed:
                self._conn = await self._connect()
            async with self._conn.transaction():
                async with self._conn.cursor() as cur:
                    i = 0
                    while i < len(batch):
                        sql = batch[i][0]
                        j = i
                        while j < len(batch) and batch[j][0] == sql:
                            j += 1
                        await cur.executemany(sql, [p for _, p in batch[i:j]])
                        i = j
        except Exception as exc:  # noqa: BLE001 - any database failure: keep the batch, retry later
            if self.ok or self.last_error != repr(exc):
                LOG.error("database batch of %d rows failed, will retry: %r", len(batch), exc)
            self.ok, self.last_error = False, repr(exc)
            await self._drop_connection()
            return False
        if epoch == self._epoch:
            for _ in range(len(batch)):
                self._queue.popleft()
        # else: a reset rebuilt the queue meanwhile; kept rows are written again (idempotent).
        self.ok, self.last_error = True, None
        self.batches += 1
        self.rows_written += len(batch)
        self.last_commit_mono = time.monotonic()
        return True

    async def _drop_connection(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                await conn.close()
            except Exception:  # noqa: BLE001 - already broken
                pass

    async def close(self) -> None:
        """Stop the task, then drain the queue (a few attempts) and close the connection."""
        self._closing = True
        self._wake.set()
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)
        for attempt in range(DRAIN_ATTEMPTS):
            if await self.flush():
                break
            await asyncio.sleep(min(2.0, 0.2 * (attempt + 1)))
        if self._queue:
            LOG.error("shutdown: %d database rows could not be written", len(self._queue))
        await self._drop_connection()
