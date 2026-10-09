"""SR-041 double-submit CSRF token: issue, rotate and verify (E09-X02 F-1, #2090).

Pure logic, no framework imports. The HTTP edge (`candleviewer.api.csrf`) sets
the cookie and enforces the header; this module only mints and checks tokens.

Token shape: ``<nonce>.<mac>`` where ``nonce`` is 32 random bytes (urlsafe
base64) and ``mac = HMAC-SHA256(key, "<session_id>|<nonce>")``. The MAC binds
the token to one session, so a new session (login, every refresh rotation)
gets a new token and a token from another session is refused (SR-041
"bound to the session and rotated with it"). Every comparison is constant time.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

CSRF_COOKIE = "cv_csrf"
CSRF_HEADER = "X-CSRF-Token"
_NONCE_BYTES = 32
_MIN_KEY_BYTES = 32


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


class CsrfTokens:
    """Mint/verify session-bound CSRF tokens with an injected server key."""

    def __init__(self, key: bytes) -> None:
        if len(key) < _MIN_KEY_BYTES:
            raise ValueError("CSRF key must be at least 32 bytes")
        self._key = key

    def _mac(self, session_id: str, nonce: str) -> str:
        msg = f"{session_id}|{nonce}".encode()
        return _b64(hmac.new(self._key, msg, hashlib.sha256).digest())

    def issue(self, session_id: str) -> str:
        """A fresh token for *session_id*; call at login and on every refresh."""
        nonce = _b64(secrets.token_bytes(_NONCE_BYTES))
        return f"{nonce}.{self._mac(session_id, nonce)}"

    def bound_to(self, token: str, session_id: str) -> bool:
        """True iff *token* was issued for *session_id* by this key."""
        nonce, sep, mac = token.partition(".")
        if not sep or not nonce or not mac:
            return False
        return hmac.compare_digest(mac.encode(), self._mac(session_id, nonce).encode())


def tokens_match(cookie: str | None, header: str | None) -> bool:
    """Double-submit check: both present, non-empty and equal (constant time)."""
    if not cookie or not header:
        return False
    return hmac.compare_digest(cookie.encode(), header.encode())
