"""Async WebSocket client with authentication, heartbeats, and reconnection."""

from __future__ import annotations

import asyncio
import json
import random
from dataclasses import dataclass
from enum import Enum
from typing import (
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Dict,
    Iterable,
    Mapping,
    Optional,
    Set,
    Tuple,
)

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from .auth import generate_signature, timestamp
from .constants import PUBLIC_WS_URLS, WS_URLS, Environment
from .exceptions import DeltaAuthenticationError, DeltaWebSocketError


class Channel(str, Enum):
    """Documented channel names. Custom string channel names are also accepted."""

    TICKER = "ticker"
    TICKER_V2 = "v2/ticker"
    L1_ORDERBOOK = "ob_l1"
    L2_ORDERBOOK = "ob_l2"
    ORDERBOOK_UPDATES = "ob_updates"
    TRADES = "trades"
    MARK_PRICE = "mark_price"
    CANDLESTICK = "candlestick"
    SPOT_PRICE = "spot_price"
    FUNDING_RATE = "funding_rate"
    PRODUCT_UPDATES = "product_updates"
    SYSTEM_STATUS = "system_status"
    MARGINS = "margins"
    POSITIONS = "positions"
    ORDERS = "orders"
    USER_TRADES = "user_trades"
    USER_TRADES_V2 = "v2/user_trades"
    PORTFOLIO_MARGINS = "portfolio_margins"
    MMP_TRIGGER = "mmp_trigger"


@dataclass(frozen=True)
class Subscription:
    name: str
    symbols: Tuple[str, ...]

    def payload(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"name": self.name}
        if self.symbols:
            data["symbols"] = list(self.symbols)
        return data


class DeltaWebSocketClient:
    """Delta streaming client designed for use as an async iterator.

    Subscriptions are retained and replayed after reconnect. If credentials are
    supplied, replay occurs only after a successful ``key-auth`` response.
    """

    def __init__(
        self,
        url: Optional[str] = None,
        *,
        environment: Environment = Environment.INDIA,
        public: bool = False,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        enable_heartbeat: bool = True,
        heartbeat_timeout: Optional[float] = 40.0,
        reconnect: bool = True,
        reconnect_min_delay: float = 1.0,
        reconnect_max_delay: float = 30.0,
    ) -> None:
        environment = Environment(environment)
        endpoints = PUBLIC_WS_URLS if public else WS_URLS
        if url is None and environment not in endpoints:
            raise ValueError(
                "No documented WebSocket URL exists for this environment; pass url explicitly"
            )
        if (api_key is None) != (api_secret is None):
            raise DeltaAuthenticationError("api_key and api_secret must be supplied together")
        if public and api_key:
            raise ValueError("authentication requires the private WebSocket endpoint")

        self.url = url or endpoints[environment]
        self.api_key = api_key
        self.api_secret = api_secret
        self.enable_heartbeat = enable_heartbeat
        self.heartbeat_timeout = heartbeat_timeout
        self.reconnect = reconnect
        self.reconnect_min_delay = reconnect_min_delay
        self.reconnect_max_delay = reconnect_max_delay
        self._connection: Any = None
        self._subscriptions: Dict[str, Set[str]] = {}
        self._authenticated = api_key is None
        self._closing = False

    async def __aenter__(self) -> "DeltaWebSocketClient":
        await self.connect()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    @property
    def connected(self) -> bool:
        return self._connection is not None

    @staticmethod
    def candlestick_channel(resolution: str) -> str:
        """Return a channel name such as ``candlestick_1m``."""
        return f"candlestick_{resolution}"

    async def _send(self, message: Mapping[str, Any]) -> None:
        if self._connection is None:
            raise DeltaWebSocketError("WebSocket is not connected")
        await self._connection.send(json.dumps(message, separators=(",", ":")))

    async def connect(self) -> None:
        if self._connection is not None:
            return
        self._closing = False
        self._authenticated = self.api_key is None
        self._connection = await connect(self.url, ping_interval=30, ping_timeout=5)
        if self.enable_heartbeat:
            await self._send({"type": "enable_heartbeat"})
        if self.api_key and self.api_secret:
            request_timestamp = timestamp()
            signature = generate_signature(self.api_secret, f"GET{request_timestamp}/live")
            await self._send(
                {
                    "type": "key-auth",
                    "payload": {
                        "api-key": self.api_key,
                        "signature": signature,
                        "timestamp": request_timestamp,
                    },
                }
            )
        else:
            await self._replay_subscriptions()

    async def close(self) -> None:
        self._closing = True
        connection, self._connection = self._connection, None
        if connection is not None:
            await connection.close()

    async def authenticate(self) -> None:
        """Send a fresh key-auth message on an existing connection."""
        if not self.api_key or not self.api_secret:
            raise DeltaAuthenticationError("api_key and api_secret are required")
        request_timestamp = timestamp()
        await self._send(
            {
                "type": "key-auth",
                "payload": {
                    "api-key": self.api_key,
                    "signature": generate_signature(
                        self.api_secret, f"GET{request_timestamp}/live"
                    ),
                    "timestamp": request_timestamp,
                },
            }
        )

    async def unauthenticate(self) -> None:
        await self._send({"type": "unauth", "payload": {}})
        self._authenticated = False

    async def subscribe(self, channel: str, symbols: Iterable[str] = ("all",)) -> None:
        name = channel.value if isinstance(channel, Channel) else str(channel)
        symbol_set = self._subscriptions.setdefault(name, set())
        added = set(symbols)
        symbol_set.update(added)
        if self._connection is not None and self._authenticated and added:
            await self._send_channels("subscribe", [Subscription(name, tuple(sorted(added)))])

    async def subscribe_many(self, channels: Iterable[Subscription]) -> None:
        new_subscriptions = []
        for subscription in channels:
            symbols = self._subscriptions.setdefault(subscription.name, set())
            added = set(subscription.symbols)
            symbols.update(added)
            new_subscriptions.append(Subscription(subscription.name, tuple(sorted(added))))
        if self._connection is not None and self._authenticated and new_subscriptions:
            await self._send_channels("subscribe", new_subscriptions)

    async def unsubscribe(self, channel: str, symbols: Optional[Iterable[str]] = None) -> None:
        name = channel.value if isinstance(channel, Channel) else str(channel)
        current = self._subscriptions.get(name, set())
        if symbols is None:
            self._subscriptions.pop(name, None)
            subscription = Subscription(name, ())
        else:
            removed = set(symbols)
            current.difference_update(removed)
            if not current:
                self._subscriptions.pop(name, None)
            subscription = Subscription(name, tuple(sorted(removed)))
        if self._connection is not None:
            await self._send_channels("unsubscribe", [subscription])

    async def _send_channels(self, action: str, subscriptions: Iterable[Subscription]) -> None:
        await self._send(
            {
                "type": action,
                "payload": {"channels": [item.payload() for item in subscriptions]},
            }
        )

    async def _replay_subscriptions(self) -> None:
        subscriptions = [
            Subscription(name, tuple(sorted(symbols)))
            for name, symbols in self._subscriptions.items()
        ]
        if subscriptions:
            await self._send_channels("subscribe", subscriptions)

    async def messages(self) -> AsyncIterator[Dict[str, Any]]:
        """Yield decoded messages, reconnecting and resubscribing when configured."""
        delay = self.reconnect_min_delay
        while not self._closing:
            try:
                if self._connection is None:
                    await self.connect()
                receive = self._connection.recv()
                if self.enable_heartbeat and self.heartbeat_timeout is not None:
                    raw_message = await asyncio.wait_for(receive, timeout=self.heartbeat_timeout)
                else:
                    raw_message = await receive
                try:
                    message = json.loads(raw_message)
                except (TypeError, json.JSONDecodeError) as exc:
                    raise DeltaWebSocketError("Received invalid JSON") from exc
                if not isinstance(message, dict):
                    raise DeltaWebSocketError("Received a non-object WebSocket message")

                if message.get("type") == "key-auth":
                    if not message.get("success"):
                        await self.close()
                        raise DeltaAuthenticationError(
                            str(
                                message.get("message")
                                or message.get("status")
                                or "WebSocket authentication failed"
                            )
                        )
                    self._authenticated = True
                    await self._replay_subscriptions()
                delay = self.reconnect_min_delay
                yield message
            except DeltaAuthenticationError:
                raise
            except (ConnectionClosed, OSError, TimeoutError) as exc:
                connection, self._connection = self._connection, None
                if connection is not None:
                    await connection.close()
                if self._closing or not self.reconnect:
                    if self._closing:
                        return
                    raise DeltaWebSocketError("WebSocket connection closed") from exc
                await asyncio.sleep(delay + random.uniform(0, delay * 0.2))
                delay = min(delay * 2, self.reconnect_max_delay)

    async def run(self, handler: Callable[[Dict[str, Any]], Awaitable[None]]) -> None:
        """Pass every incoming message to an async callback."""
        async for message in self.messages():
            await handler(message)
