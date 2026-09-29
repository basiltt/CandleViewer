"""Bybit v5 REST request signing (`docs/plan/24-internal-schemas.md` §14.3
"Auth (REST)"; ticket body scenario "Signature matches the specification").

`X-BAPI-SIGN` = `HMAC-SHA256(timestamp + api_key + recv_window + payload)`,
hex-encoded, where `payload` is the query string for `GET` and the raw JSON
body for `POST`. The secret key is held as `pydantic.SecretStr` end to end
and is never formatted into a log line, exception message or `repr()`
(security notes: "keys are held as `SecretStr` and never formatted into
strings").
"""

from __future__ import annotations

import hashlib
import hmac

from pydantic import SecretStr


class BybitSigner:
    """Stateless signer for one `(api_key, api_secret)` pair.

    Construction takes `SecretStr` so a caller cannot accidentally pass a
    bare `str` that later gets logged; `sign` reads the secret value only
    for the duration of the HMAC call and never stores it as a plain
    attribute.
    """

    def __init__(self, api_key: str, api_secret: SecretStr) -> None:
        self.api_key = api_key
        self._api_secret = api_secret

    def sign(self, *, timestamp_ms: int, recv_window_ms: int, payload: str) -> str:
        """Return the lowercase hex HMAC-SHA256 signature for one request.

        `payload` is the query string (no leading `?`) for `GET`/`DELETE`
        requests or the exact JSON body string for `POST` requests — the
        caller must pass the same bytes that are actually sent, since the
        signature covers them verbatim.
        """
        message = f"{timestamp_ms}{self.api_key}{recv_window_ms}{payload}"
        secret_bytes = self._api_secret.get_secret_value().encode("utf-8")
        # HMAC-SHA256 is the Bybit v5 request-signing algorithm mandated by the
        # exchange API spec (docs/plan/24-internal-schemas.md §14.3) — this is
        # message-authentication keyed hashing of a request, not password
        # storage hashing, so SHA-256's speed is not a weakness here.
        digest = hmac.new(
            secret_bytes,
            message.encode("utf-8"),
            hashlib.sha256,  # lgtm[py/insufficient-hash-strength]
        )
        return digest.hexdigest()

    @staticmethod
    def verify(*, expected_hex: str, actual_hex: str) -> bool:
        """Constant-time comparison, used by tests validating a fixture
        vector — production code never needs to *verify* its own outgoing
        signature, but `hmac.compare_digest` is the mandated comparison
        primitive per the security notes whenever a signature comparison
        occurs."""
        return hmac.compare_digest(expected_hex, actual_hex)

    def __repr__(self) -> str:  # pragma: no cover - trivial, but asserted by a test
        return f"BybitSigner(api_key={self.api_key!r}, api_secret=**redacted**)"
