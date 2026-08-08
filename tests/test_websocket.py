import json

import pytest

from delta_rest_ws import Channel, DeltaAuthenticationError, DeltaWebSocketClient


class FakeConnection:
    def __init__(self, messages):
        self.messages = iter(messages)
        self.sent = []
        self.closed = False

    async def send(self, message):
        self.sent.append(json.loads(message))

    async def recv(self):
        return next(self.messages)

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_public_client_replays_preconnected_subscriptions(monkeypatch):
    connection = FakeConnection([json.dumps({"type": "ticker", "symbol": "BTCUSD"})])

    async def fake_connect(*args, **kwargs):
        return connection

    monkeypatch.setattr("delta_rest_ws.websocket.connect", fake_connect)
    client = DeltaWebSocketClient(url="wss://example.test", public=True, reconnect=False)
    await client.subscribe(Channel.TICKER, ["BTCUSD"])

    message = await client.messages().__anext__()

    assert message["symbol"] == "BTCUSD"
    assert connection.sent[0] == {"type": "enable_heartbeat"}
    assert connection.sent[1]["type"] == "subscribe"
    assert connection.sent[1]["payload"]["channels"] == [{"name": "ticker", "symbols": ["BTCUSD"]}]


@pytest.mark.asyncio
async def test_private_subscriptions_wait_for_auth(monkeypatch):
    connection = FakeConnection([json.dumps({"type": "key-auth", "success": True})])

    async def fake_connect(*args, **kwargs):
        return connection

    monkeypatch.setattr("delta_rest_ws.websocket.connect", fake_connect)
    monkeypatch.setattr("delta_rest_ws.websocket.timestamp", lambda: "123")
    client = DeltaWebSocketClient(
        url="wss://example.test", api_key="key", api_secret="secret", reconnect=False
    )
    await client.subscribe(Channel.ORDERS, ["all"])

    message = await client.messages().__anext__()

    assert message["success"] is True
    assert connection.sent[1]["type"] == "key-auth"
    assert connection.sent[1]["payload"]["timestamp"] == "123"
    assert connection.sent[2]["type"] == "subscribe"


@pytest.mark.asyncio
async def test_authentication_failure_is_not_retried(monkeypatch):
    connection = FakeConnection(
        [json.dumps({"type": "key-auth", "success": False, "message": "bad signature"})]
    )

    async def fake_connect(*args, **kwargs):
        return connection

    monkeypatch.setattr("delta_rest_ws.websocket.connect", fake_connect)
    client = DeltaWebSocketClient(
        url="wss://example.test", api_key="key", api_secret="secret", reconnect=True
    )

    with pytest.raises(DeltaAuthenticationError, match="bad signature"):
        await client.messages().__anext__()
    assert connection.closed
