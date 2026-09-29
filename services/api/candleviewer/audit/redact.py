"""Redaction layer for `before_state`/`after_state` (ticket "Scope /
Deliverables": "removes any field classified SECRET ... and hashes PII where
the value itself is not needed").

Fail-closed by design (ticket "Security notes": "a redactor with a
fail-closed default — unknown fields in a SECRET-classified object are
dropped, not passed"): `redact()` only ever *removes or replaces* data, it
never lets an un-recognised nested structure pass through unexamined —
dicts are walked recursively and lists element-wise, so a field nested three
levels deep is caught exactly like a top-level one.

The field-name registry below is deliberately name-based (not type-based):
every column comment in `0001_identity_rbac_sessions_mfa.py` marked `SECRET`
or `PII` names the exact field this list mirrors 1:1
(`password_hash`, TOTP `secret`, `recovery_codes.code_hash`,
`sessions.refresh_token_hash`, invite tokens, API keys). A field name is
matched case-insensitively and after stripping common separators, so
`passwordHash`, `password_hash` and `PASSWORD-HASH` are all caught.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

REDACTION_MARKER = "<redacted:secret>"
PII_HASH_PREFIX = "<hashed:pii>:"

#: Name fragments that mark a field as SECRET — dropped entirely, replaced
#: with `REDACTION_MARKER`. Matched against the normalised (lowercased,
#: separators stripped) field name as a substring, so `totp_seed`,
#: `totpSeed`, `mfa_secret` are all covered by `secret`/`seed`/`token`/`hash`.
_SECRET_FIELD_FRAGMENTS: frozenset[str] = frozenset(
    {
        "passwordhash",
        "password",
        "secret",
        "totpseed",
        "seed",
        "recoverycode",
        "refreshtoken",
        "accesstoken",
        "invitetoken",
        "apikey",
        "privatekey",
        "signature",
        "dek",
        "kek",
        "token",
        "hash",
    }
)

#: Exact (normalised) field names that mark a field as PII — matched exactly,
#: not as substrings (a substring match on `ip` would hash `description`,
#: `recipient`, ...). The value is replaced with a SHA-256 digest
#: (`PII_HASH_PREFIX` + hex) rather than dropped, so
#: correlation (e.g. "same IP as this other entry") stays possible without
#: storing the raw value (ticket: "hashes PII where the value itself is not
#: needed").
_PII_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "email",
        "actorip",
        "ip",
        "ipaddress",
        "sourceip",
        "useragent",
        "displayname",
        "phonenumber",
        "phone",
    }
)

#: Exact (normalised: lowercased, every non-alphanumeric stripped) field
#: names that are credentials in their own right (security review of PR #1561,
#: finding 3): HTTP auth headers, exchange request-signing headers (`X-BAPI-SIGN`),
#: one-time codes, session identifiers and bearer tokens. Exact match, not
#: substring, so `sign` does not redact `design`/`assign`. `recv_window` is
#: deliberately absent — it is a timing parameter, not a secret.
_SECRET_EXACT_NAMES: frozenset[str] = frozenset(
    {
        "authorization",
        "proxyauthorization",
        "cookie",
        "setcookie",
        "bearer",
        "credential",
        "credentials",
        "passphrase",
        "sign",
        "signature",
        "xbapisign",
        "xbapiapikey",
        "otp",
        "totp",
        "otpcode",
        "totpcode",
        "mfacode",
        "session",
        "sid",
        "sessionid",
        "jwt",
        "idtoken",
        "accesstoken",
        "refreshtoken",
        "privatekey",
    }
)

#: snake_case suffixes (after camelCase/kebab-case are folded to snake_case)
#: that mark a field as SECRET: `secret_key`, `webhookSecret`, `csrf-token`.
_SECRET_SUFFIXES: tuple[str, ...] = ("_key", "_secret", "_token", "_password")

#: A field literally named `code` is a one-time code when it sits next to an
#: OTP marker (`{"method": "totp", "code": "123456"}` / `{"totp": ..., "code": ...}`).
_OTP_MARKERS: frozenset[str] = frozenset({"otp", "totp", "mfa"})

_NORMALISE_RE = re.compile(r"[^a-z0-9]")
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _normalise(name: str) -> str:
    return _NORMALISE_RE.sub("", name.lower())


def _snake(name: str) -> str:
    return _CAMEL_RE.sub("_", name).lower().replace("-", "_")


def _classify(field_name: str) -> str | None:
    normalised = _normalise(field_name)
    if normalised in _SECRET_EXACT_NAMES or _snake(field_name).endswith(_SECRET_SUFFIXES):
        return "secret"
    for fragment in _SECRET_FIELD_FRAGMENTS:
        if fragment in normalised:
            return "secret"
    if normalised in _PII_FIELD_NAMES:
        return "pii"
    return None


def _hash_pii(value: Any) -> str:
    digest = hashlib.sha256(repr(value).encode("utf-8")).hexdigest()
    return f"{PII_HASH_PREFIX}{digest}"


def redact(state: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a redacted copy of `state` (or `None` if `state` is `None`).

    Never mutates the input. SECRET-classified fields (by name, see
    `_SECRET_FIELD_FRAGMENTS`) become `REDACTION_MARKER`; PII-classified
    fields become a SHA-256 digest of their `repr`; everything else is walked
    recursively (nested dicts/lists) so a SECRET value nested under an
    unclassified parent key is still caught.
    """
    if state is None:
        return None
    return _redact_mapping(state)


def _has_otp_sibling(mapping: dict[str, Any]) -> bool:
    for key, value in mapping.items():
        norm_key = _normalise(key)
        if any(marker in norm_key for marker in _OTP_MARKERS):
            return True
        if isinstance(value, str) and _normalise(value) in _OTP_MARKERS:
            return True
    return False


def _redact_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    otp_context = _has_otp_sibling(mapping)
    for key, value in mapping.items():
        classification = _classify(key)
        if classification is None and otp_context and _normalise(key) == "code":
            classification = "secret"
        if classification == "secret":
            out[key] = REDACTION_MARKER
        elif classification == "pii":
            out[key] = _hash_pii(value) if value is not None else None
        elif isinstance(value, dict):
            out[key] = _redact_mapping(value)
        elif isinstance(value, list):
            out[key] = _redact_sequence(value)
        else:
            out[key] = value
    return out


def _redact_sequence(items: list[Any]) -> list[Any]:
    redacted: list[Any] = []
    for item in items:
        if isinstance(item, dict):
            redacted.append(_redact_mapping(item))
        elif isinstance(item, list):
            redacted.append(_redact_sequence(item))
        else:
            redacted.append(item)
    return redacted
