# Delta Exchange Python SDK

A typed Python client for the Delta Exchange v2 REST API and real-time WebSocket feed.
It is based on the API snapshot in [`docs/delta-exchange-api-docs.md`](docs/delta-exchange-api-docs.md).

> This is a community SDK. Test trading code on the demo environment before using real funds.

## Features

- Public and signed REST requests
- Helpers for market data, orders, positions, wallets, account settings, MMP, and deadman switch
- Generic `request()` method for newly released v2 endpoints
- Cursor pagination iterator
- Async WebSocket client with `key-auth`, heartbeat monitoring, reconnection, and subscription replay
- Built-in India/global REST and India WebSocket endpoint selection
- Structured exceptions and complete type hints

## Install

```bash
pip install delta-rest-ws
```

Python 3.9 or newer is required.

## REST quick start

Public endpoints need no credentials:

```python
from delta_rest_ws import DeltaRestClient, Environment

client = DeltaRestClient(environment=Environment.INDIA_TESTNET)

products = client.get_products({"states": "live"})
ticker = client.get_ticker("BTCUSD")
candles = client.get_candles(
    symbol="BTCUSD",
    resolution="5m",
    start=1722511635,
    end=1722598035,
)
client.close()
```

Private endpoints are signed automatically:

```python
from delta_rest_ws import DeltaRestClient, Environment, OrderType

with DeltaRestClient(
    environment=Environment.INDIA_TESTNET,
    api_key="YOUR_API_KEY",
    api_secret="YOUR_API_SECRET",
) as client:
    order = client.place_order(
        product_id=27,
        size=1,
        side="buy",
        order_type=OrderType.LIMIT,
        limit_price="50000",
        client_order_id="strategy-001",
    )
    client.cancel_order(product_id=27, order_id=order["id"])
```

Do not commit API credentials. Read them from environment variables or a secrets manager.

### Environments

| Environment | REST | Private WebSocket | Public WebSocket |
|---|---|---|---|
| `INDIA` | `https://api.india.delta.exchange` | `wss://socket.india.delta.exchange` | `wss://public-socket.india.delta.exchange` |
| `INDIA_TESTNET` | `https://cdn-ind.testnet.deltaex.org` | `wss://socket-ind.testnet.deltaex.org` | `wss://socket-ind-pub.testnet.deltaex.org` |
| `GLOBAL` | `https://api.delta.exchange` | Pass `url=` explicitly | Pass `url=` explicitly |
| `GLOBAL_TESTNET` | `https://testnet-api.delta.exchange` | Pass `url=` explicitly | Pass `url=` explicitly |

The bundled API documentation only declares India WebSocket URLs, so the SDK does not guess
global socket endpoints.

### Pagination

```python
for page in client.iter_pages(
    "/fills",
    query={"contract_types": "perpetual_futures"},
):
    for fill in page:
        print(fill)
```

`order_history()` and `fills()` return the full API envelope so `result` and `meta.after`
remain available. Most other helpers return the `result` value directly.

### Calling a new endpoint

```python
result = client.request(
    "GET",
    "/v2/some_future_endpoint",
    query={"symbol": "BTCUSD"},
    auth=True,
)
```

## WebSocket quick start

Subscriptions may be registered before connecting. They are sent on connect and restored after
any reconnect.

```python
import asyncio

from delta_rest_ws import Channel, DeltaWebSocketClient, Environment


async def main():
    ws = DeltaWebSocketClient(
        environment=Environment.INDIA_TESTNET,
        public=True,
    )
    await ws.subscribe(Channel.TICKER, ["BTCUSD", "ETHUSD"])
    await ws.subscribe("candlestick_1m", ["MARK:BTCUSD"])

    try:
        async for message in ws.messages():
            print(message)
    finally:
        await ws.close()


asyncio.run(main())
```

Private streams authenticate before subscriptions are sent:

```python
ws = DeltaWebSocketClient(
    environment=Environment.INDIA_TESTNET,
    api_key="YOUR_API_KEY",
    api_secret="YOUR_API_SECRET",
)
await ws.subscribe(Channel.ORDERS, ["all"])
await ws.subscribe(Channel.POSITIONS, ["all"])

async for message in ws.messages():
    print(message)
```

The client enables Delta's server heartbeat and uses a 40-second receive timeout by default.
It also sends WebSocket ping frames every 30 seconds and expects a pong within 5 seconds.

## Errors

```python
from delta_rest_ws import DeltaAPIError, DeltaHTTPError

try:
    client.get_profile()
except DeltaHTTPError as error:
    print(error.status_code, error)
except DeltaAPIError as error:
    print(error.code, error.context, error)
```

## Development

```bash
python -m pip install -e ".[dev]"
ruff check .
pytest
python -m build
python -m twine check dist/*
```

## Publishing to PyPI

1. Choose and register the final distribution name. `delta-rest-client` is already owned by the
   official Delta maintainers. The current metadata uses `delta-rest-ws`; name availability
   can change until the first upload claims it.
2. Update the version in both `pyproject.toml` and `src/delta_rest_ws/__init__.py`.
3. Run the development checks above.
4. Prefer a PyPI Trusted Publisher from CI, or upload manually with
   `python -m twine upload dist/*` using an API token.

Publishing is intentionally not automated from a developer machine because it requires the
owner's PyPI account and explicit release authorization.

## License

MIT License.
