"""Real TCP Uvicorn + websockets tests, without a broker or database."""
import asyncio
from contextlib import contextmanager
import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus, ConnectionClosed
from sw_common import make_verdict, topic_for

from sw_api.app import create_app


@contextmanager
def server_for(bus, clock):
    app = create_app(bus=bus, clock=clock)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, loop="asyncio", http="h11", ws="websockets-sansio", log_level="error", lifespan="on"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise AssertionError("Uvicorn did not start")
            time.sleep(.01)
        yield app, port
    finally:
        server.should_exit = True
        thread.join(5)
        listener.close()
        assert not thread.is_alive(), "Uvicorn did not shut down"
        assert bus.closed


def test_real_network_ws_snapshot_cookie_token_origin_and_immediate_verdict(bus, clock):
    with server_for(bus, clock) as (app, port):
        base = f"http://127.0.0.1:{port}"
        with httpx.Client(base_url=base) as client:
            response = client.post("/api/session", json={"role": "nurse"})
            assert response.status_code == 200
            token = response.json()["token"]
            cookie = f"sw_session={client.cookies.get('sw_session')}"
        async def run():
            url = f"ws://127.0.0.1:{port}/ws"
            with pytest.raises(InvalidStatus) as rejected:
                async with connect(url):
                    pass
            assert rejected.value.response.status_code == 403
            with pytest.raises(InvalidStatus):
                async with connect(url, origin="https://evil.example", additional_headers={"Cookie": cookie}):
                    pass
            async with connect(url, origin=base, additional_headers={"Cookie": cookie}) as ws:
                snapshot = [json.loads(await asyncio.wait_for(ws.recv(), 2)) for _ in range(12)]
                assert [m["payload"]["bed_id"] for m in snapshot] == [f"B{i:02d}" for i in range(1, 13)]
                assert all(m["type"] == "bed.updated" for m in snapshot)
                verdict = make_verdict(bed_id="B05", window_start=clock.ms()//5000*5000, verdict="EMERGENCY", confidence=.9, trust=.9, scores={}, ts=clock.ms())
                start = time.perf_counter()
                worker = threading.Thread(target=app.state.runtime.ingest.callback, args=(verdict, topic_for(verdict)))
                worker.start()
                worker.join()
                while True:
                    event = json.loads(await asyncio.wait_for(ws.recv(), 2))
                    if event["type"] == "bed.updated" and event["payload"]["bed_id"] == "B05":
                        break
                elapsed = time.perf_counter() - start
                assert event["payload"]["verdict"] == "EMERGENCY"
                assert elapsed < .1, f"verdict took {elapsed:.3f}s"
                # Expiring the cookie session closes an already connected socket.
                clock.advance(28801)
                with pytest.raises(ConnectionClosed) as closed:
                    while True:
                        await asyncio.wait_for(ws.recv(), 3)
                assert closed.value.rcvd.code == 1008
            # Fresh session tests explicit query and Bearer credentials over TCP.
            async with httpx.AsyncClient(base_url=base) as http:
                fresh = (await http.post("/api/session", json={"role": "it"})).json()["token"]
            for extra in ({"uri": url+"?token="+fresh}, {"uri": url, "additional_headers": {"Authorization": "Bearer "+fresh}}):
                async with connect(**extra) as ws:
                    assert json.loads(await ws.recv())["type"] == "bed.updated"
        asyncio.run(run())
