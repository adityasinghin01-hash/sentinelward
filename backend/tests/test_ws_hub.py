"""Fan-out ordering, bounded buffering and telemetry pacing without sockets."""
import asyncio

from sw_api.ws import Hub


class Clock:
    def __init__(self):
        self.now = 0.0

    def mono(self):
        return self.now


def bed_message(bed_id="B01", hr=70):
    return {"type": "bed.updated", "payload": {"bed_id": bed_id, "vitals": {"hr": hr}}}


def test_initial_snapshot_is_wrapped_and_precedes_live_events():
    async def check():
        hub = Hub()
        first = {"bed_id": "B01"}
        client = hub.subscribe([first, {"bed_id": "B02"}])
        first["bed_id"] = "changed"
        hub.broadcast(bed_message(hr=80))
        assert await client.get() == {"type": "bed.updated", "payload": {"bed_id": "B01"}}
        assert await client.get() == {"type": "bed.updated", "payload": {"bed_id": "B02"}}
        assert await client.get() == bed_message(hr=80)
    asyncio.run(check())


def test_telemetry_coalesces_to_latest_value_per_bed_each_second():
    async def check():
        clock = Clock()
        hub = Hub(clock)
        client = hub.subscribe([])
        hub.broadcast(bed_message(hr=70), critical=False)
        assert await client.get() == bed_message(hr=70)
        clock.now = 0.1
        hub.broadcast(bed_message(hr=71), critical=False)
        clock.now = 0.9
        hub.broadcast(bed_message(hr=79), critical=False)
        hub.broadcast(bed_message("B02", 90), critical=False)
        assert await client.get() == bed_message("B02", 90)
        hub.flush()
        assert client.qsize == 0
        clock.now = 1.0
        hub.flush()
        assert client.qsize == 1
        assert await client.get() == bed_message(hr=79)
        hub.flush()
        assert client.qsize == 0
    asyncio.run(check())


def test_new_telemetry_replaces_pending_value_when_due_without_double_send():
    async def check():
        clock = Clock()
        hub = Hub(clock)
        client = hub.subscribe([])
        hub.broadcast(bed_message(hr=70), critical=False)
        await client.get()
        clock.now = 0.3
        hub.broadcast(bed_message(hr=71), critical=False)
        clock.now = 1.1
        hub.broadcast(bed_message(hr=80), critical=False)
        hub.flush()
        assert client.qsize == 1
        assert await client.get() == bed_message(hr=80)
    asyncio.run(check())


def test_critical_update_is_immediate_and_removes_stale_pending_telemetry():
    async def check():
        clock = Clock()
        hub = Hub(clock)
        client = hub.subscribe([])
        hub.broadcast(bed_message(hr=70), critical=False)
        await client.get()
        clock.now = 0.2
        hub.broadcast(bed_message(hr=71), critical=False)
        hub.broadcast(bed_message(hr=99))
        assert await client.get() == bed_message(hr=99)
        clock.now = 1.1
        hub.flush()
        assert client.qsize == 0
    asyncio.run(check())


def test_connection_events_bypass_telemetry_pacing():
    async def check():
        hub = Hub(Clock())
        client = hub.subscribe([])
        event = {"type": "connection.changed", "payload": {"state": "disconnected", "occurred_at": 42}}
        hub.broadcast(event)
        assert await client.get() == event
    asyncio.run(check())


def test_soft_queue_limit_discards_telemetry_before_critical_events():
    async def check():
        hub = Hub(Clock())
        client = hub.subscribe([])
        for value in range(500):
            hub.broadcast(bed_message(hr=value))
        hub.broadcast(bed_message("B02", 5), critical=False)
        hub.broadcast(bed_message(hr=500))
        assert client.qsize == 501
        assert not client.closed
        observed = [await client.get() for _ in range(501)]
        assert [message["payload"]["vitals"]["hr"] for message in observed] == list(range(501))
    asyncio.run(check())


def test_hard_queue_limit_closes_client_and_wakes_waiter_on_unsubscribe():
    async def check():
        hub = Hub()
        client = hub.subscribe([])
        for value in range(2000):
            hub.broadcast(bed_message(hr=value))
        assert not client.closed
        hub.broadcast(bed_message(hr=2000))
        assert client.closed
        assert await client.get() is None
        waiting_client = hub.subscribe([])
        waiting = asyncio.create_task(waiting_client.get())
        await asyncio.sleep(0)
        hub.unsubscribe(waiting_client)
        assert await asyncio.wait_for(waiting, 0.2) is None
        hub.unsubscribe(waiting_client)
    asyncio.run(check())


def test_broadcast_wakes_waiting_clients_and_unsubscribe_removes_client():
    async def check():
        hub = Hub()
        first, second = hub.subscribe([]), hub.subscribe([])
        waiting = asyncio.create_task(first.get())
        await asyncio.sleep(0)
        hub.broadcast(bed_message())
        assert await asyncio.wait_for(waiting, 0.2) == bed_message()
        assert await second.get() == bed_message()
        hub.unsubscribe(first)
        hub.broadcast(bed_message(hr=77))
        assert await first.get() is None
        assert await second.get() == bed_message(hr=77)
    asyncio.run(check())
