import asyncio

import pytest

# Kerberos is disabled via environment variables in conftest.py

from app.services.websocket_service import ConnectionManager


class SlowWebSocket:
    def __init__(self, started_event: asyncio.Event, release_event: asyncio.Event):
        self._started_event = started_event
        self._release_event = release_event
        self.messages = []

    async def send_json(self, message):
        self.messages.append(message)
        self._started_event.set()
        await self._release_event.wait()


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio("asyncio")
async def test_broadcast_allows_subscribe_and_disconnect_during_send():
    manager = ConnectionManager()
    started = asyncio.Event()
    release = asyncio.Event()
    websocket = SlowWebSocket(started, release)

    async with manager._lock:
        manager.active_connections["client1"] = websocket
        manager.subscriptions["client1"] = {"topic"}

    broadcast_task = asyncio.create_task(
        manager.broadcast({"payload": "data"}, topic="topic")
    )

    await asyncio.wait_for(started.wait(), timeout=1)

    await asyncio.wait_for(manager.subscribe("client1", ["extra"]), timeout=0.5)
    assert "extra" in manager.subscriptions["client1"]

    await asyncio.wait_for(manager.disconnect("client1"), timeout=0.5)

    release.set()

    await asyncio.wait_for(broadcast_task, timeout=1)

    assert "client1" not in manager.active_connections
    assert websocket.messages == [{"payload": "data"}]
