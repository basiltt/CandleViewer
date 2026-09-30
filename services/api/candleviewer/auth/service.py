"""Lifecycle contract for the auth module (M18).

Every module implements the lifecycle contract from
`docs/plan/20-architecture.md` Sec.3: `start`, `stop`, `health`. E09-S01
wires `LoginService` when a real `UserRepository` is injected (mirrors
`AuditService`'s "`is_active` until a real backend is wired" pattern);
without one (fake/CI-default backend) it stays the no-op scaffold so
`create_app()`/tests keep working without a database. E09-S02 additionally
wires `MfaService` when an `MfaRepository` is injected, using the same
`is_active` gate, and hands `LoginService` the same `MfaRepository` so it
can persist the `mfa_challenges` row the two-legged login flow shares.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from candleviewer.auth.envelope import LOCAL_KEY_REF, TotpEncryptor
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.login_service import LoginService
from candleviewer.auth.mfa_service import MfaService
from candleviewer.observability.health import HealthReport, HealthStatus

if TYPE_CHECKING:
    from candleviewer.app import AppContext
    from candleviewer.auth.mfa_repository import MfaRepository
    from candleviewer.auth.repository import UserRepository


class AuthService:
    """M18 `auth` module lifecycle.

    `login`/`mfa` are `None` until `start()` has wired a real backend;
    callers (the `api` router) must check `is_active`/`mfa_is_active`
    first."""

    def __init__(
        self,
        repository: UserRepository | None = None,
        *,
        pepper: str = "",
        mfa_repository: MfaRepository | None = None,
        totp_encryption_key: bytes | None = None,
    ) -> None:
        self._started = False
        self._repository = repository
        self._pepper = pepper
        self._mfa_repository = mfa_repository
        self._totp_encryption_key = totp_encryption_key
        self._login: LoginService | None = None
        self._mfa: MfaService | None = None

    @property
    def is_active(self) -> bool:
        return self._login is not None

    @property
    def login(self) -> LoginService:
        if self._login is None:
            raise RuntimeError("AuthService.start() has not wired a real backend")
        return self._login

    @property
    def mfa_is_active(self) -> bool:
        return self._mfa is not None

    @property
    def mfa(self) -> MfaService:
        if self._mfa is None:
            raise RuntimeError("AuthService.start() has not wired an MfaRepository")
        return self._mfa

    async def start(self, ctx: AppContext) -> None:
        """Start the module. Wires `LoginService`/`MfaService` only when a
        concrete repository was injected by the composition root;
        otherwise stays the no-op scaffold. `auth` never imports a storage
        driver (ADR-0003 import-linter contract)."""
        if self._repository is not None:
            self._login = LoginService(
                self._repository, Hasher(pepper=self._pepper), mfa_repository=self._mfa_repository
            )
        if self._mfa_repository is not None:
            # `totp_encryption_key` stands in for the real M2 KEK wiring
            # (see `envelope.py`'s module docstring for why M18 cannot
            # import `candleviewer.secrets` itself); a caller that omits it
            # gets a fresh process-local key each start, which is fine for
            # tests/dev but must be replaced before any real deployment —
            # tracked as this ticket's own documented gap, same shape as
            # `Hasher`'s `pepper=""` default.
            key = self._totp_encryption_key or _process_local_key()
            self._mfa = MfaService(self._mfa_repository, TotpEncryptor(key, key_ref=LOCAL_KEY_REF))
        self._started = True

    async def stop(self, grace_s: float) -> None:
        """Stop the module within `grace_s` seconds. No-op scaffold."""
        self._login = None
        self._mfa = None
        self._started = False

    def health(self) -> HealthReport:
        """Report module health. Scaffold modules report `ok` when constructed."""
        status = HealthStatus.OK if self._started else HealthStatus.STOPPED
        detail = "" if self.is_active else "scaffold module — no repository wired"
        return HealthReport(module="auth", status=status, detail=detail)


def _process_local_key() -> bytes:
    return os.urandom(32)
