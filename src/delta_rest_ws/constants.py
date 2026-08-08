"""URLs and enums used by the SDK."""

from enum import Enum


class Environment(str, Enum):
    INDIA = "india"
    INDIA_TESTNET = "india_testnet"
    GLOBAL = "global"
    GLOBAL_TESTNET = "global_testnet"


REST_URLS = {
    Environment.INDIA: "https://api.india.delta.exchange",
    Environment.INDIA_TESTNET: "https://cdn-ind.testnet.deltaex.org",
    Environment.GLOBAL: "https://api.delta.exchange",
    Environment.GLOBAL_TESTNET: "https://testnet-api.delta.exchange",
}

# The bundled documentation specifies WebSocket endpoints for India.
WS_URLS = {
    Environment.INDIA: "wss://socket.india.delta.exchange",
    Environment.INDIA_TESTNET: "wss://socket-ind.testnet.deltaex.org",
}

PUBLIC_WS_URLS = {
    Environment.INDIA: "wss://public-socket.india.delta.exchange",
    Environment.INDIA_TESTNET: "wss://socket-ind-pub.testnet.deltaex.org",
}


class OrderType(str, Enum):
    MARKET = "market_order"
    LIMIT = "limit_order"


class TimeInForce(str, Enum):
    FOK = "fok"
    IOC = "ioc"
    GTC = "gtc"
