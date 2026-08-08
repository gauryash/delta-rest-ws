import json

from delta_rest_ws.auth import body_string, generate_signature, query_string, sign_request


def test_signature_matches_known_sha256_hmac_vector():
    # RFC 4231 test case 2.
    assert generate_signature("Jefe", "what do ya want for nothing?") == (
        "5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843"
    )


def test_request_serialization_is_compact_and_deterministic():
    payload = {"size": 3, "tags": ["a", "b"]}
    query = {"symbol": "MARK:BTCUSD", "states": ["live", "expired"]}

    assert body_string(payload) == json.dumps(payload, separators=(",", ":"))
    assert query_string(query) == "?symbol=MARK%3ABTCUSD&states=live&states=expired"
    assert sign_request("secret", "GET", "1", "/v2/test", query, payload) == generate_signature(
        "secret",
        "GET1/v2/test?symbol=MARK%3ABTCUSD&states=live&states=expired" + body_string(payload),
    )
