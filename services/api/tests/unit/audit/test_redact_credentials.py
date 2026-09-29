"""Credential-name coverage for `redact()` (PR #1561 security finding 3):
every listed name, in snake/camel/kebab/upper variants, is redacted; `code`
only next to an OTP marker; non-secrets (`recv_window`, `design`) pass."""

from __future__ import annotations

import pytest

from candleviewer.audit.redact import REDACTION_MARKER, redact

_SECRET_NAMES = (
    "authorization",
    "Authorization",
    "cookie",
    "Cookie",
    "set-cookie",
    "Set-Cookie",
    "bearer",
    "credential",
    "credentials",
    "passphrase",
    "sign",
    "signature",
    "X-BAPI-SIGN",
    "x_bapi_sign",
    "otp",
    "totp",
    "totp_code",
    "totpCode",
    "session",
    "sid",
    "session_id",
    "sessionId",
    "jwt",
    "id_token",
    "access_token",
    "accessToken",
    "refresh_token",
    "private_key",
    "apiKey",
    "api_key",
    "secret_key",
    "SECRET_KEY",
    "webhook_secret",
    "csrf-token",
    "db_password",
)


@pytest.mark.parametrize("name", _SECRET_NAMES)
def test_redact_credential_name_is_redacted(name: str) -> None:
    out = redact({name: "s3cr3t-value", "nested": {name: "s3cr3t-value"}})
    assert out == {name: REDACTION_MARKER, "nested": {name: REDACTION_MARKER}}


@pytest.mark.parametrize(
    "state",
    [
        {"method": "totp", "code": "123456"},
        {"otp_required": True, "code": "123456"},
        {"mfa": "on", "code": "123456"},
    ],
)
def test_redact_code_next_to_otp_marker_is_redacted(state: dict[str, object]) -> None:
    out = redact(state)
    assert out is not None and out["code"] == REDACTION_MARKER


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("recv_window", "5000"),
        ("design", "x"),
        ("assign", "x"),
        ("code", "ERR_42"),
        ("monkey", "x"),
        ("symbol", "BTCUSDT"),
    ],
)
def test_redact_non_secret_passes_through(name: str, value: str) -> None:
    assert redact({name: value}) == {name: value}


def test_redact_bare_key_is_secret() -> None:
    """PR #1561 N4: a field literally named `key` is a credential."""
    from candleviewer.audit.redact import REDACTION_MARKER, redact

    assert redact({"key": "abc", "monkey": "ok"}) == {"key": REDACTION_MARKER, "monkey": "ok"}


def test_redact_embedded_json_string_is_redacted() -> None:
    import json

    from candleviewer.audit.redact import REDACTION_MARKER, redact

    out = redact({"body": '{"api_key":"LEAK"}', "list": '[{"token":"LEAK"}]', "n": "{bad"})
    assert out is not None
    assert "LEAK" not in json.dumps(out)
    assert json.loads(out["body"]) == {"api_key": REDACTION_MARKER}
    assert json.loads(out["list"]) == [{"token": REDACTION_MARKER}]
    assert out["n"] == "{bad"
    assert redact({"s": "[1]", "q": '"x"', "e": ""}) == {"s": "[1]", "q": '"x"', "e": ""}


def test_redact_embedded_json_bounded_depth_and_size() -> None:
    import json

    from candleviewer.audit.redact import OVERSIZE_MARKER, redact

    nested: object = {"api_key": "LEAK"}
    for _ in range(6):
        nested = {"inner": json.dumps(nested)}
    out = redact({"x": json.dumps(nested)})
    assert out is not None and "LEAK" not in json.dumps(out) and OVERSIZE_MARKER in json.dumps(out)
    big = redact({"b": "[" + "1," * 40000 + "1]"})
    assert big == {"b": OVERSIZE_MARKER}
