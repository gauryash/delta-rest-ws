import json

import pytest

from delta_rest_ws import DeltaAPIError, DeltaAuthenticationError, DeltaHTTPError
from delta_rest_ws.rest import DeltaRestClient


class FakeResponse:
    def __init__(self, data, status_code=200, content=None):
        self._data = data
        self.status_code = status_code
        self.text = json.dumps(data)
        self.content = content if content is not None else self.text.encode()

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.headers = {}
        self.calls = []
        self.closed = False

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return next(self.responses)

    def close(self):
        self.closed = True


def test_public_request_unwraps_result_and_encodes_query():
    session = FakeSession([FakeResponse({"success": True, "result": {"mark_price": "1"}})])
    client = DeltaRestClient(base_url="https://example.test/", session=session)

    result = client.get_ticker("BTC USD")

    assert result == {"mark_price": "1"}
    method, url, kwargs = session.calls[0]
    assert method == "GET"
    assert url == "https://example.test/v2/tickers/BTC%20USD"
    assert kwargs["data"] is None


def test_private_request_signs_exact_url(monkeypatch):
    session = FakeSession([FakeResponse({"success": True, "result": []})])
    client = DeltaRestClient(
        base_url="https://example.test", api_key="key", api_secret="secret", session=session
    )
    monkeypatch.setattr("delta_rest_ws.rest.timestamp", lambda: "123")

    client.get_live_orders({"product_id": 1, "state": "open"})

    _, url, kwargs = session.calls[0]
    assert url == "https://example.test/v2/orders?product_id=1&state=open"
    assert kwargs["headers"]["api-key"] == "key"
    assert kwargs["headers"]["timestamp"] == "123"
    assert len(kwargs["headers"]["signature"]) == 64


def test_private_request_requires_credentials():
    client = DeltaRestClient(base_url="https://example.test", session=FakeSession([]))
    with pytest.raises(DeltaAuthenticationError):
        client.get_profile()


def test_http_and_api_errors_are_structured():
    session = FakeSession(
        [
            FakeResponse({"error": {"code": "unauthorized", "message": "No"}}, 401),
            FakeResponse(
                {
                    "success": False,
                    "error": {"code": "bad_order", "message": "Bad", "context": {"x": 1}},
                }
            ),
        ]
    )
    client = DeltaRestClient(
        base_url="https://example.test", api_key="key", api_secret="secret", session=session
    )

    with pytest.raises(DeltaHTTPError) as http_error:
        client.get_profile()
    assert http_error.value.status_code == 401

    with pytest.raises(DeltaAPIError) as api_error:
        client.get_profile()
    assert api_error.value.code == "bad_order"
    assert api_error.value.context == {"x": 1}


def test_pagination_follows_after_cursor():
    session = FakeSession(
        [
            FakeResponse({"success": True, "result": [1], "meta": {"after": "next"}}),
            FakeResponse({"success": True, "result": [2], "meta": {"after": None}}),
        ]
    )
    client = DeltaRestClient(
        base_url="https://example.test", api_key="key", api_secret="secret", session=session
    )

    assert list(client.iter_pages("/fills")) == [[1], [2]]
    assert "after=next" in session.calls[1][1]


def test_limit_order_validates_price_and_serializes_values():
    session = FakeSession([FakeResponse({"success": True, "result": {"id": 5}})])
    client = DeltaRestClient(
        base_url="https://example.test", api_key="key", api_secret="secret", session=session
    )

    with pytest.raises(ValueError):
        client.place_order(27, 1, "buy")

    assert client.place_order(27, 2, "buy", limit_price=42.5) == {"id": 5}
    payload = json.loads(session.calls[0][2]["data"])
    assert payload["limit_price"] == "42.5"
    assert payload["post_only"] is False
