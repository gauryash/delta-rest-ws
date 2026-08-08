"""Synchronous client for the Delta Exchange v2 REST API."""

from __future__ import annotations

from typing import Any, Dict, Iterator, Mapping, MutableMapping, Optional, Sequence, Union
from urllib.parse import quote

import requests

from . import __version__
from .auth import Query, body_string, query_string, sign_request, timestamp
from .constants import REST_URLS, Environment, OrderType, TimeInForce
from .exceptions import DeltaAPIError, DeltaAuthenticationError, DeltaHTTPError

Identifier = Union[int, str]


def _without_none(values: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    return {key: value for key, value in (values or {}).items() if value is not None}


def _segment(value: Identifier) -> str:
    return quote(str(value), safe=":,.@-")


class DeltaRestClient:
    """A small, typed wrapper over all documented Delta Exchange v2 endpoints.

    Args:
        base_url: Explicit REST origin. When omitted, ``environment`` is used.
        api_key: API key for private endpoints.
        api_secret: API secret for request signing.
        environment: Built-in endpoint selection.
        timeout: Requests connect/read timeout in seconds.
        session: Optional custom :class:`requests.Session`.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        *,
        environment: Environment = Environment.INDIA,
        timeout: Union[float, tuple[float, float]] = (3.0, 27.0),
        session: Optional[requests.Session] = None,
    ) -> None:
        self.base_url = (base_url or REST_URLS[Environment(environment)]).rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.setdefault("Accept", "application/json")
        self.session.headers.setdefault("Content-Type", "application/json")
        self.session.headers.setdefault("User-Agent", f"delta-rest-ws/{__version__}")

    def __enter__(self) -> "DeltaRestClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self.session.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: Any = None,
        query: Query = None,
        auth: bool = False,
        unwrap: bool = True,
        raw: bool = False,
        headers: Optional[Mapping[str, str]] = None,
    ) -> Any:
        """Call any v2 endpoint, including endpoints added after this SDK release."""
        method = method.upper()
        if not path.startswith("/"):
            path = f"/{path}"
        if not path.startswith("/v2/") and path != "/v2":
            path = f"/v2{path}"

        body = body_string(payload)
        qs = query_string(query)
        request_headers: MutableMapping[str, str] = dict(headers or {})
        if auth:
            if not self.api_key or not self.api_secret:
                raise DeltaAuthenticationError("api_key and api_secret are required")
            request_timestamp = timestamp()
            request_headers.update(
                {
                    "api-key": self.api_key,
                    "timestamp": request_timestamp,
                    "signature": sign_request(
                        self.api_secret, method, request_timestamp, path, query, payload
                    ),
                }
            )

        response = self.session.request(
            method,
            f"{self.base_url}{path}{qs}",
            data=body or None,
            headers=request_headers,
            timeout=self.timeout,
        )
        if not 200 <= response.status_code < 300:
            message = f"Delta HTTP {response.status_code}"
            try:
                error_body = response.json()
                error = error_body.get("error", error_body)
                if isinstance(error, Mapping):
                    message = str(error.get("message") or error.get("code") or error)
                else:
                    message = str(error)
            except (ValueError, AttributeError):
                if response.text:
                    message = response.text
            raise DeltaHTTPError(message, response.status_code, response)

        if raw:
            return response.content
        try:
            data = response.json()
        except ValueError as exc:
            raise DeltaAPIError("Delta returned invalid JSON", response=response) from exc
        if not isinstance(data, Mapping):
            return data
        if data.get("success") is False:
            error = data.get("error", {})
            if isinstance(error, Mapping):
                message = str(error.get("message") or error.get("code") or "Delta API error")
                code = error.get("code")
                context = error.get("context")
            else:
                message, code, context = str(error), None, None
            raise DeltaAPIError(message, code=code, context=context, response=response)
        return data.get("result") if unwrap and "result" in data else data

    def iter_pages(
        self,
        path: str,
        *,
        query: Optional[Mapping[str, Any]] = None,
        page_size: int = 100,
        auth: bool = True,
    ) -> Iterator[Any]:
        """Yield results while following Delta's ``meta.after`` cursor."""
        params = _without_none(query)
        params["page_size"] = page_size
        while True:
            envelope = self.request("GET", path, query=params, auth=auth, unwrap=False)
            yield envelope.get("result")
            after = envelope.get("meta", {}).get("after")
            if not after:
                break
            params["after"] = after

    # Market data
    def get_assets(self, *, auth: bool = False) -> Any:
        return self.request("GET", "/assets", auth=auth)

    def get_indices(self, *, auth: bool = False) -> Any:
        return self.request("GET", "/indices", auth=auth)

    def get_products(self, query: Optional[Mapping[str, Any]] = None, *, auth: bool = False) -> Any:
        return self.request("GET", "/products", query=_without_none(query), auth=auth)

    def get_product(self, identifier: Identifier, *, auth: bool = False) -> Any:
        return self.request("GET", f"/products/{_segment(identifier)}", auth=auth)

    def get_tickers(self, query: Optional[Mapping[str, Any]] = None, *, auth: bool = False) -> Any:
        return self.request("GET", "/tickers", query=_without_none(query), auth=auth)

    def get_ticker(self, symbol: str, *, auth: bool = False) -> Any:
        return self.request("GET", f"/tickers/{_segment(symbol)}", auth=auth)

    def get_option_chain(
        self, underlying_asset_symbol: str, expiry_date: Optional[str] = None
    ) -> Any:
        return self.get_tickers(
            _without_none(
                {
                    "contract_types": "call_options,put_options",
                    "underlying_asset_symbols": underlying_asset_symbol,
                    "expiry_date": expiry_date,
                }
            )
        )

    option_chain = get_option_chain

    def get_l2_orderbook(self, symbol: Identifier, *, auth: bool = False) -> Any:
        return self.request("GET", f"/l2orderbook/{_segment(symbol)}", auth=auth)

    def get_public_trades(self, symbol: str, *, auth: bool = False) -> Any:
        return self.request("GET", f"/trades/{_segment(symbol)}", auth=auth)

    def get_candles(self, symbol: str, resolution: str, start: int, end: int) -> Any:
        return self.request(
            "GET",
            "/history/candles",
            query={"resolution": resolution, "symbol": symbol, "start": start, "end": end},
        )

    def get_sparklines(self, symbols: Union[str, Sequence[str]]) -> Any:
        value = ",".join(symbols) if not isinstance(symbols, str) else symbols
        return self.request("GET", "/history/sparklines", query={"symbols": value})

    def get_stats(self) -> Any:
        return self.request("GET", "/stats")

    def get_rate_limit_quota(self) -> Any:
        return self.request("GET", "/rate_limits/quota")

    # Orders
    def create_order(self, order: Mapping[str, Any]) -> Any:
        return self.request("POST", "/orders", payload=dict(order), auth=True)

    def place_order(
        self,
        product_id: int,
        size: int,
        side: str,
        limit_price: Optional[Union[str, float]] = None,
        time_in_force: Optional[TimeInForce] = None,
        order_type: OrderType = OrderType.LIMIT,
        post_only: bool = False,
        client_order_id: Optional[str] = None,
        reduce_only: bool = False,
        **extra: Any,
    ) -> Any:
        order: Dict[str, Any] = {
            "product_id": product_id,
            "size": int(size),
            "side": side,
            "order_type": OrderType(order_type).value,
            "post_only": post_only,
            "reduce_only": reduce_only,
            **extra,
        }
        if OrderType(order_type) is OrderType.LIMIT:
            if limit_price is None:
                raise ValueError("limit_price is required for a limit order")
            order["limit_price"] = str(limit_price)
        if time_in_force is not None:
            order["time_in_force"] = TimeInForce(time_in_force).value
        if client_order_id is not None:
            order["client_order_id"] = client_order_id
        return self.create_order(order)

    def place_stop_order(
        self,
        product_id: int,
        size: int,
        side: str,
        *,
        stop_price: Optional[Union[str, float]] = None,
        limit_price: Optional[Union[str, float]] = None,
        trail_amount: Optional[Union[str, float]] = None,
        order_type: OrderType = OrderType.MARKET,
        **extra: Any,
    ) -> Any:
        if stop_price is None and trail_amount is None:
            raise ValueError("stop_price or trail_amount is required")
        order: Dict[str, Any] = {
            "product_id": product_id,
            "size": int(size),
            "side": side,
            "order_type": OrderType(order_type).value,
            "stop_order_type": "stop_loss_order",
            **extra,
        }
        if OrderType(order_type) is OrderType.LIMIT:
            if limit_price is None:
                raise ValueError("limit_price is required for a limit stop order")
            order["limit_price"] = str(limit_price)
        if trail_amount is not None:
            amount = abs(float(trail_amount)) * (1 if side == "buy" else -1)
            order["trail_amount"] = str(amount)
        else:
            order["stop_price"] = str(stop_price)
        return self.create_order(order)

    def edit_order(self, order: Mapping[str, Any]) -> Any:
        return self.request("PUT", "/orders", payload=dict(order), auth=True)

    def cancel_order(self, product_id: int, order_id: int) -> Any:
        return self.request(
            "DELETE", "/orders", payload={"id": order_id, "product_id": product_id}, auth=True
        )

    def cancel_all_orders(self, payload: Optional[Mapping[str, Any]] = None) -> Any:
        return self.request("DELETE", "/orders/all", payload=dict(payload or {}), auth=True)

    def get_live_orders(self, query: Optional[Mapping[str, Any]] = None) -> Any:
        return self.request("GET", "/orders", query=_without_none(query), auth=True)

    get_active_orders = get_live_orders

    def get_order_by_id(self, order_id: int) -> Any:
        return self.request("GET", f"/orders/{_segment(order_id)}", auth=True)

    def get_order_by_client_id(self, client_oid: str) -> Any:
        return self.request("GET", f"/orders/client_order_id/{_segment(client_oid)}", auth=True)

    def batch_create(self, product_id: int, orders: Sequence[Mapping[str, Any]]) -> Any:
        return self.request(
            "POST",
            "/orders/batch",
            payload={"product_id": product_id, "orders": list(orders)},
            auth=True,
        )

    def batch_edit(self, product_id: int, orders: Sequence[Mapping[str, Any]]) -> Any:
        return self.request(
            "PUT",
            "/orders/batch",
            payload={"product_id": product_id, "orders": list(orders)},
            auth=True,
        )

    def batch_cancel(self, product_id: int, orders: Sequence[Mapping[str, Any]]) -> Any:
        return self.request(
            "DELETE",
            "/orders/batch",
            payload={"product_id": product_id, "orders": list(orders)},
            auth=True,
        )

    def place_bracket_order(self, order: Mapping[str, Any]) -> Any:
        return self.request("POST", "/orders/bracket", payload=dict(order), auth=True)

    def edit_bracket_order(self, order: Mapping[str, Any]) -> Any:
        return self.request("PUT", "/orders/bracket", payload=dict(order), auth=True)

    def order_history(
        self,
        query: Optional[Mapping[str, Any]] = None,
        page_size: int = 100,
        after: Optional[str] = None,
    ) -> Any:
        params = _without_none(query)
        params.update(_without_none({"page_size": page_size, "after": after}))
        return self.request("GET", "/orders/history", query=params, auth=True, unwrap=False)

    def fills(
        self,
        query: Optional[Mapping[str, Any]] = None,
        page_size: int = 100,
        after: Optional[str] = None,
    ) -> Any:
        params = _without_none(query)
        params.update(_without_none({"page_size": page_size, "after": after}))
        return self.request("GET", "/fills", query=params, auth=True, unwrap=False)

    def download_fills(self, query: Optional[Mapping[str, Any]] = None) -> bytes:
        return self.request(
            "GET", "/fills/history/download/csv", query=_without_none(query), auth=True, raw=True
        )

    # Positions and leverage
    def set_leverage(self, product_id: int, leverage: Union[str, int, float]) -> Any:
        return self.request(
            "POST",
            f"/products/{_segment(product_id)}/orders/leverage",
            payload={"leverage": leverage},
            auth=True,
        )

    def get_order_leverage(self, product_id: int) -> Any:
        return self.request("GET", f"/products/{_segment(product_id)}/orders/leverage", auth=True)

    def get_position(self, product_id: Optional[int] = None) -> Any:
        return self.request(
            "GET", "/positions", query=_without_none({"product_id": product_id}), auth=True
        )

    def get_margined_positions(
        self, product_ids: Optional[Union[str, Sequence[int]]] = None
    ) -> Any:
        value = product_ids
        if product_ids is not None and not isinstance(product_ids, str):
            value = ",".join(map(str, product_ids))
        return self.request(
            "GET", "/positions/margined", query=_without_none({"product_ids": value}), auth=True
        )

    def get_margined_position(self, product_id: int) -> Any:
        positions = self.get_margined_positions([product_id])
        return positions[0] if positions else None

    def change_position_margin(self, product_id: int, delta_margin: Union[str, float]) -> Any:
        return self.request(
            "POST",
            "/positions/change_margin",
            payload={"product_id": product_id, "delta_margin": delta_margin},
            auth=True,
        )

    def auto_topup_position(self, product_id: int, auto_topup: bool) -> Any:
        return self.request(
            "PUT",
            "/positions/auto_topup",
            payload={"product_id": product_id, "auto_topup": auto_topup},
            auth=True,
        )

    def close_all_positions(self, **options: Any) -> Any:
        return self.request(
            "POST", "/positions/close_all", payload=_without_none(options), auth=True
        )

    # Wallet and account
    def get_all_wallet_balances(self) -> Any:
        return self.request("GET", "/wallet/balances", auth=True)

    def get_balances(self, asset_id: Optional[int] = None) -> Any:
        balances = self.get_all_wallet_balances()
        if asset_id is None:
            return balances
        return next((item for item in balances if item.get("asset_id") == asset_id), None)

    def get_wallet_transactions(self, query: Optional[Mapping[str, Any]] = None) -> Any:
        return self.request("GET", "/wallet/transactions", query=_without_none(query), auth=True)

    def download_wallet_transactions(self, query: Optional[Mapping[str, Any]] = None) -> bytes:
        return self.request(
            "GET", "/wallet/transactions/download", query=_without_none(query), auth=True, raw=True
        )

    def transfer_subaccount_balance(self, transfer: Mapping[str, Any]) -> Any:
        return self.request(
            "POST", "/wallets/sub_account_balance_transfer", payload=dict(transfer), auth=True
        )

    def get_subaccount_transfer_history(self, query: Optional[Mapping[str, Any]] = None) -> Any:
        return self.request(
            "GET", "/wallets/sub_accounts_transfer_history", query=_without_none(query), auth=True
        )

    def get_profile(self) -> Any:
        return self.request("GET", "/profile", auth=True)

    def get_subaccounts(self) -> Any:
        return self.request("GET", "/sub_accounts", auth=True)

    def change_margin_mode(self, margin_mode: str, subaccount_user_id: Optional[str] = None) -> Any:
        return self.request(
            "PUT",
            "/users/margin_mode",
            payload=_without_none(
                {"margin_mode": margin_mode, "subaccount_user_id": subaccount_user_id}
            ),
            auth=True,
        )

    def get_trading_preferences(self) -> Any:
        return self.request("GET", "/users/trading_preferences", auth=True)

    def update_trading_preferences(self, preferences: Mapping[str, Any]) -> Any:
        return self.request(
            "PUT", "/users/trading_preferences", payload=dict(preferences), auth=True
        )

    def update_mmp(self, config: Mapping[str, Any]) -> Any:
        return self.request("PUT", "/users/update_mmp", payload=dict(config), auth=True)

    def reset_mmp(self, payload: Mapping[str, Any]) -> Any:
        return self.request("PUT", "/users/reset_mmp", payload=dict(payload), auth=True)

    # Deadman switch / heartbeat
    def create_heartbeat(self, config: Mapping[str, Any]) -> Any:
        return self.request("POST", "/heartbeat/create", payload=dict(config), auth=True)

    def acknowledge_heartbeat(self, heartbeat_id: str, ttl: int) -> Any:
        return self.request(
            "POST", "/heartbeat", payload={"heartbeat_id": heartbeat_id, "ttl": ttl}, auth=True
        )

    def get_heartbeats(self, user_id: Optional[int] = None) -> Any:
        return self.request(
            "GET", "/heartbeat", query=_without_none({"user_id": user_id}), auth=True
        )


def create_order_format(
    price: Union[str, float], size: int, side: str, product_id: int, post_only: bool = False
) -> Dict[str, Any]:
    return {
        "product_id": product_id,
        "limit_price": str(price),
        "size": int(size),
        "side": side,
        "order_type": OrderType.LIMIT.value,
        "post_only": post_only,
    }


def cancel_order_format(order: Mapping[str, Any]) -> Dict[str, Any]:
    return {"id": order["id"], "product_id": order["product_id"]}
