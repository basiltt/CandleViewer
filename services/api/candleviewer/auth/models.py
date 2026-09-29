"""Domain models for the auth module (M18): password sign-in (E09-S01).

Pydantic v2 request/result types for `POST /auth/login`, matching
`docs/plan/22-api-openapi.yaml` `LoginRequest`/`LoginResponse`/`TokenBundle`/
`MfaChallengeResponse`. The row-shaped `UserRecord` mirrors the columns
`0001_identity_rbac_sessions_mfa.py` created that this ticket's scope reads
or writes; it is a plain read/write DTO for `UserRepository`, not the
`User` API schema (which additionally carries roles/permissions assembled
elsewhere).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class UserStatus(StrEnum):
    INVITED = "invited"
    ACTIVE = "active"
    DISABLED = "disabled"
    LOCKED = "locked"


class MfaMethodKind(StrEnum):
    TOTP = "totp"
    WEBAUTHN = "webauthn"
    RECOVERY_CODE = "recovery_code"


class LoginRequest(BaseModel):
    """`docs/plan/22-api-openapi.yaml` `LoginRequest`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    identifier: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=512)
    device_name: str | None = Field(default=None, max_length=120)


class TokenBundle(BaseModel):
    """`docs/plan/22-api-openapi.yaml` `TokenBundle`.

    Real token minting (the `cv_refresh` cookie, JWT `access_token`
    contents, session-row creation) is E09-S03 scope ("Session lifetime,
    idle lock and revocation semantics" — this ticket's own "Out of scope").
    `LoginService` therefore never constructs one; the router only ever
    returns `MfaChallengeResponse` today, matching this story's own scope
    ("`/auth/mfa/verify` (E09-S02) completes it")."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    access_token: str
    token_type: str = "Bearer"  # noqa: S105 - not a secret, it's the RFC 6750 scheme name
    expires_in: int
    refresh_expires_in: int | None = None
    refresh_token: str | None = None


class MfaChallengeResult(BaseModel):
    """Successful-credentials outcome: an MFA challenge was issued.

    `mfa_token` is opaque to the router — `LoginService` returns the raw
    value once, at issuance, and never re-derives or re-exposes it (only
    `mfa_token_hash` is persisted, mirroring `sessions.refresh_token_hash`'s
    pattern of never storing a bearer secret in the clear)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mfa_token: str
    methods: tuple[MfaMethodKind, ...]
    expires_in: int = 300


class UserRecord(BaseModel):
    """Row-shaped view of `users` columns this ticket's scope touches.

    Not the API-facing `User` schema (no roles/permissions — those come
    from `user_roles`/`role_permissions`, out of this story's scope).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: uuid.UUID
    username: str
    email: str
    password_hash: str
    password_algo_params: dict[str, int]
    status: UserStatus
    mfa_required: bool
    failed_login_count: int
    locked_until: datetime | None
    mfa_methods: tuple[MfaMethodKind, ...] = ()
