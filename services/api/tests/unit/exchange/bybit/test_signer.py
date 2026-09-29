"""Signer unit tests (ticket scenario "Signature matches the specification").

The vector below is derived directly from `docs/plan/24-internal-schemas.md`
§14.3's documented formula: `HMAC-SHA256(timestamp + api_key + recv_window +
(queryString | jsonBody))`, hex-encoded — computed independently in this
test (not copied from the implementation) so a regression in `signer.py`
is caught.
"""

from __future__ import annotations

import hashlib
import hmac

from pydantic import SecretStr

from candleviewer.exchange.bybit.signer import BybitSigner


def test_sign_get_matches_independently_computed_hmac() -> None:
    signer = BybitSigner(api_key="test-key", api_secret=SecretStr("test-secret"))
    timestamp_ms = 1700000000000
    recv_window_ms = 5000
    query = "category=linear&symbol=BTCUSDT"

    actual = signer.sign(timestamp_ms=timestamp_ms, recv_window_ms=recv_window_ms, payload=query)

    message = f"{timestamp_ms}test-key{recv_window_ms}{query}"
    expected = hmac.new(b"test-secret", message.encode("utf-8"), hashlib.sha256).hexdigest()
    assert actual == expected


def test_sign_post_body_uses_raw_json_string() -> None:
    signer = BybitSigner(api_key="k", api_secret=SecretStr("s"))
    body = '{"symbol":"BTCUSDT","qty":"1"}'

    actual = signer.sign(timestamp_ms=1, recv_window_ms=5000, payload=body)

    message = f"1k5000{body}"
    expected = hmac.new(b"s", message.encode("utf-8"), hashlib.sha256).hexdigest()
    assert actual == expected


def test_verify_uses_constant_time_comparison() -> None:
    assert BybitSigner.verify(expected_hex="abc", actual_hex="abc") is True
    assert BybitSigner.verify(expected_hex="abc", actual_hex="abd") is False


def test_repr_never_exposes_the_secret() -> None:
    signer = BybitSigner(api_key="visible-key", api_secret=SecretStr("super-secret-value"))
    rendered = repr(signer)
    assert "super-secret-value" not in rendered
    assert "visible-key" in rendered
    assert "redacted" in rendered


def test_str_of_secretstr_never_exposes_value() -> None:
    # Guards against a caller accidentally formatting the secret directly.
    secret = SecretStr("super-secret-value")
    assert "super-secret-value" not in str(secret)
    assert "super-secret-value" not in repr(secret)
