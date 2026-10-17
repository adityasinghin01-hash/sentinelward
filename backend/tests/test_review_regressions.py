"""Hostile review of cross-component ordering and reset boundaries."""
import asyncio
from dataclasses import replace

from sw_api.app import create_app
from sw_api.config import Settings
from sw_api.state import Point
from sw_api.store import MemoryStore
from sw_common import make_verdict


def test_delayed_trusted_point_lookup_cannot_repopulate_reset_bed(bus, clock):
    async def check():
        store = MemoryStore()
        runtime = create_app(settings=replace(Settings(), pg_dsn='memory'),
                             bus=bus, store=store, clock=clock).state.runtime
        started, finish = asyncio.Event(), asyncio.Event()
        old = Point(ts=clock.ms()-1000, received_ms=clock.ms(), seq=1, hr=61,
                    spo2=97, rr=16, sys=None, dia=None, map=None, nibp_ts=None,
                    abp_mean=None, alarm_code=None, alarm_priority=None,
                    verdict='NORMAL', trusted=True, bp=None)
        async def delayed_point(*args):
            started.set()
            await finish.wait()
            return old
        store.trusted_point_async = delayed_point
        task = asyncio.create_task(runtime._lookup('B05', old.ts, True))
        await started.wait()
        runtime.reset()
        finish.set()
        await task
        # A fresh run must never acquire old values as a trusted pin.
        clock.advance(1)
        runtime.state.on_verdict(make_verdict(bed_id='B05', ts=clock.ms(),
            window_start=clock.ms()//5000*5000, verdict='TAMPERING', confidence=1,
            trust=0, last_trusted_ts=old.ts, scores={}))
        assert runtime.state.beds['B05'].pin is None
    asyncio.run(check())


def test_out_of_range_demo_seek_is_rejected_before_clearing_ward(bus, clock):
    from fastapi.testclient import TestClient
    from sw_common import make_vitals, topic_for
    app = create_app(settings=replace(Settings(), pg_dsn='memory'), bus=bus, clock=clock)
    with TestClient(app) as client:
        assert client.post('/api/session', json={'role': 'operator'}).status_code == 200
        message = make_vitals(bed_id='B01', seq=1, ts=clock.ms(), hr=70)
        assert client.portal.call(app.state.runtime.ingest.process, message, topic_for(message))
        response = client.post('/api/demo/run', json={'start_at_s': 1200})
        assert response.status_code == 422
        assert client.get('/api/ward').json()['beds'][0]['vitals']['hr'] == 70
        assert not bus.sent


def test_postgres_warm_start_barrier_includes_run_that_cleared_old_state(clock):
    """Execute the persistence SELECT against real rows; other warm tables are empty."""
    import sqlite3
    from sw_api.postgres import PostgresStore
    async def check():
        with sqlite3.connect(':memory:') as database:
            database.row_factory = sqlite3.Row
            database.execute('CREATE TABLE demo_runs (cmd TEXT, ts BIGINT)')
            database.executemany('INSERT INTO demo_runs VALUES (?, ?)',
                                 [('reset', 10000), ('run', 20000)])
            store = PostgresStore('unused', None, None, clock)
            async def query(sql, params=()):
                if 'demo_runs' in sql:
                    return [dict(row) for row in database.execute(sql, params)]
                return []
            store._query = query
            warm = await store.load()
            assert warm.reset_at == 20000
    asyncio.run(check())


def test_lookup_queued_before_reset_cannot_start_in_new_generation(bus, clock):
    from sw_common import make_vitals
    async def check():
        store = MemoryStore()
        store.sync_lookups = False
        runtime = create_app(settings=replace(Settings(), pg_dsn='memory'),
                             bus=bus, store=store, clock=clock).state.runtime
        old = Point(ts=clock.ms()-1000, received_ms=clock.ms(), seq=1, hr=61,
                    spo2=97, rr=16, sys=None, dia=None, map=None, nibp_ts=None,
                    abp_mean=None, alarm_code=None, alarm_priority=None,
                    verdict='NORMAL', trusted=True, bp=None)
        async def old_point(*args):
            return old
        store.trusted_point_async = old_point
        runtime.state.on_vitals(make_vitals(bed_id='B05', seq=2, ts=clock.ms(), hr=150))
        runtime.state.on_verdict(make_verdict(bed_id='B05', ts=clock.ms(),
            window_start=clock.ms()//5000*5000, verdict='TAMPERING', confidence=1,
            trust=0, last_trusted_ts=old.ts, scores={}))
        runtime.push_bed('B05')
        tasks = list(runtime._lookup_tasks)
        assert tasks
        runtime.reset()  # No yield: lookup tasks have been scheduled but have not started.
        await asyncio.gather(*tasks, return_exceptions=True)
        assert runtime.state.beds['B05'].pin is None
    asyncio.run(check())
