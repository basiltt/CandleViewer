"""Lifecycle contract for the auth module (M18).

Every module implements the lifecycle contract from
`docs/plan/20-architecture.md` Sec.3: `start`, `stop`, `health`. E09-S01
wires `LoginService` when a real `UserRepository` is injected (mirrors
`AuditService`'s "`is_active` until a real backend is wired" pattern);
without one (fake/CI-default backend) it stays the no-op scaffold so
`create_app()`/tests keep working without a database.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from candleviewer.auth.hashing import Hasher
from candleviewer.auth.login_service import LoginService
from candleviewer.observability.health import HealthReport, HealthStatus

if TYPE_CHECKING:
    from candleviewer.app import AppContext
    from candleviewer.auth.repository import UserRepository


class AuthService:
    """M18 `auth` module lifecycle.

    `login` is `None` until `start()` has wired a real backend; callers
    (the `api` router) must check `is_active` first."""

    def __init__(self, repository: UserRepository | None = None, *, pepper: str = "") -> None:
        self._started = False
        self._repository = repository
        self._pepper = pepper
        self._login: LoginService | None = None

    @property
    def is_active(self) -> bool:
        return self._login is not None

    @property
    def login(self) -> LoginService:
        if self._login is None:
            raise RuntimeError("AuthService.start() has not wired a real backend")
        return self._login

    async def start(self, ctx: AppContext) -> None:
        """Start the module. Wires `LoginService` only when a concrete
        `UserRepository` was injected by the composition root; otherwise
        stays the no-op scaffold. `auth` never imports a storage driver
        (ADR-0003 import-linter contract)."""
        if self._repository is not None:
            self._login = LoginService(self._repository, Hasher(pepper=self._pepper))
        self._started = True

    async def stop(self, grace_s: float) -> None:
        """Stop the module within `grace_s` seconds. No-op scaffold."""
        self._login = None
        self._started = False

    def health(self) -> HealthReport:
        """Report module health. Scaffold modules report `ok` when constructed."""
        status = HealthStatus.OK if self._started else HealthStatus.STOPPED
        detail = "" if self.is_active else "scaffold module — no repository wired"
        return HealthReport(module="auth", status=status, detail=detail)
