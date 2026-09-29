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
