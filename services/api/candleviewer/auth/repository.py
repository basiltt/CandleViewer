"""`UserRepository` — the storage-facing seam `LoginService` depends on
instead of a raw SQL driver (mirrors `candleviewer.audit.repository.AuditRepository`).

`candleviewer.auth` may not import a storage driver directly (ADR-0003,
`.importlinter` `forbidden-storage-drivers-M18`); the concrete implementation
(`candleviewer.storage.repositories.auth_sqlalchemy.SqlAlchemyUserRepository`,
this ticket's own follow-up wiring) lives in M10 and is structurally
compatible with this Protocol without either module importing the other's
types — the composition root injects it into `AuthService(repository=...)`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from candleviewer.auth.models import UserRecord


class UserRepository(Protocol):
    """Everything `LoginService` needs from the relational tier, expressed
    without any SQL-driver type in its signatures."""

    async def find_by_identifier(self, identifier: str) -> UserRecord | None:
        """Look up by `username` or `email` (case-insensitive `citext`
        columns), or `None` if no such user exists. Never raises for an
        unknown identifier — the enumeration-resistance guarantee is built
        on this returning cleanly so `LoginService` can still run a dummy
        Argon2id verification and take the identical code path."""
        ...

    async def record_login_success(self, user_id: str) -> None:
        """Reset `failed_login_count` to 0, clear `locked_until`, stamp
        `last_login_at`/`last_login_ip`. Called only after a real password
        match on an active, unlocked account."""
        ...

    async def record_login_failure(self, user_id: str, *, lock_until: datetime | None) -> None:
        """Increment `failed_login_count` by 1; if `lock_until` is given,
        also set `users.locked_until` (the fifth consecutive failure)."""
        ...

    async def rehash_password(
        self, user_id: str, *, password_hash: str, algo_params: dict[str, int]
    ) -> None:
        """Persist a re-hashed `password_hash`/`password_algo_params` after
        a successful verification against out-of-date Argon2id parameters
        (ticket "transparent rehash-on-login when parameters change")."""
        ...
