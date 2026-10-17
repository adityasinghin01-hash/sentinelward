"""BatchWriter behaviour with a fake connection (no PostgreSQL needed)."""
import asyncio
from contextlib import asynccontextmanager

from sw_api.writer import BatchWriter


class FakeConn:
    def __init__(self, log, fail):
        self.log, self.fail, self.closed = log, fail, False

    @asynccontextmanager
    async def transaction(self):
        pending = []
        self.pending = pending
        yield
        self.log.append(list(pending))  # commit

    @asynccontextmanager
    async def cursor(self):
        yield self

    async def executemany(self, sql, rows):
        if self.fail():
            raise ConnectionError("database down")
        self.pending.append((sql, list(rows)))

    async def close(self):
        self.closed = True


def make_writer(interval=0.05):
    commits, state = [], {"fail": False, "connects": 0}

    async def connect():
        state["connects"] += 1
        return FakeConn(commits, lambda: state["fail"])
    return BatchWriter(connect, interval), commits, state


def test_consecutive_statements_grouped_in_order_one_commit():
    async def run():
        w, commits, _ = make_writer()
        for sql, p in [("A", 1), ("A", 2), ("B", 3), ("A", 4)]:
            w.put(sql, p)
        assert await w.flush()
        assert commits == [[("A", [1, 2]), ("B", [3]), ("A", [4])]]
        assert w.queued == 0 and w.ok
    asyncio.run(run())


def test_failed_batch_is_retried_whole_and_reconnects():
    async def run():
        w, commits, state = make_writer()
        w.put("A", 1)
        state["fail"] = True
        assert not await w.flush()
        assert w.queued == 1 and not w.ok and commits == []
        state["fail"] = False
        w.put("A", 2)
        assert await w.flush()
        assert commits == [[("A", [1, 2])]] and state["connects"] == 2
    asyncio.run(run())


def test_background_task_commits_about_once_per_interval_and_close_drains():
    async def run():
        w, commits, _ = make_writer(interval=0.1)
        w.start()
        for i in range(20):
            w.put("V", i)
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.15)
        assert 1 <= len(commits) <= 4
        w.put("V", 99)
        await w.close()
        assert sum(len(rows) for batch in commits for _, rows in batch) == 21
        assert w.queued == 0
    asyncio.run(run())


def test_discard_during_reset_keeps_selected_rows():
    async def run():
        w, commits, _ = make_writer()
        for sql in ["vitals", "demo", "vitals"]:
            w.put(sql, 0)
        w.discard(lambda sql: sql == "demo")
        w.put("delete", 1)
        await w.flush()
        assert commits == [[("demo", [0]), ("delete", [1])]]
    asyncio.run(run())
