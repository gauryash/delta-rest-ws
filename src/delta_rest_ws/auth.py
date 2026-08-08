"""Request signing helpers shared by REST and WebSocket clients."""

import hashlib
import hmac
import json
import time
from typing import Any, Mapping, Optional, Sequence, Tuple, Union
from urllib.parse import urlencode

QueryValue = Union[str, int, float, bool, Sequence[Union[str, int, float, bool]]]
Query = Optional[Union[Mapping[str, QueryValue], Sequence[Tuple[str, QueryValue]]]]


def timestamp() -> str:
    return str(int(time.time()))


def generate_signature(secret: str, message: str) -> str:
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def body_string(payload: Any) -> str:
    return "" if payload is None else json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def query_string(query: Query) -> str:
    if not query:
        return ""
    encoded = urlencode(query, doseq=True)
    return f"?{encoded}" if encoded else ""


def sign_request(
    secret: str,
    method: str,
    request_timestamp: str,
    path: str,
    query: Query = None,
    payload: Any = None,
) -> str:
    message = method.upper() + request_timestamp + path + query_string(query) + body_string(payload)
    return generate_signature(secret, message)
