"""In-memory `UserRepository` fake for auth unit tests. No database, no network."""

from __future__ import annotations

import uuid
from datetime import datetime

from candleviewer.auth.models import MfaMethodKind, UserRecord, UserStatus
from candleviewer.auth.repository import UserRepository


class FakeUserRepository(UserRepository):
    def __init__(self) -> None:
        self.users: dict[str, UserRecord] = {}
        self.rehash_calls: list[tuple[str, str, dict[str, int]]] = []

    def add(self, user: UserRecord) -> None:
        self.users[str(user.id)] = user

    async def find_by_identifier(self, identifier: str) -> UserRecord | None:
        needle = identifier.lower()
        for user in self.users.values():
            if user.username.lower() == needle or user.email.lower() == needle:
                return user
        return None

    async def record_login_success(self, user_id: str) -> None:
        user = self.users[user_id]
        self.users[user_id] = user.model_copy(
            update={"failed_login_count": 0, "locked_until": None}
        )

    async def record_login_failure(self, user_id: str, *, lock_until: datetime | None) -> None:
        user = self.users[user_id]
        update: dict[str, object] = {"failed_login_count": user.failed_login_count + 1}
        if lock_until is not None:
            update["locked_until"] = lock_until
        self.users[user_id] = user.model_copy(update=update)

    async def rehash_password(
        self, user_id: str, *, password_hash: str, algo_params: dict[str, int]
    ) -> None:
        self.rehash_calls.append((user_id, password_hash, algo_params))
        user = self.users[user_id]
        self.users[user_id] = user.model_copy(
            update={"password_hash": password_hash, "password_algo_params": algo_params}
        )


def make_user(
    *,
    username: str = "basiltt",
    email: str = "owner@example.com",
    password_hash: str,
    status: UserStatus = UserStatus.ACTIVE,
    mfa_required: bool = True,
    mfa_methods: tuple[MfaMethodKind, ...] = (MfaMethodKind.TOTP,),
    failed_login_count: int = 0,
    locked_until: datetime | None = None,
    algo_params: dict[str, int] | None = None,
) -> UserRecord:
    return UserRecord(
        id=uuid.uuid4(),
        username=username,
        email=email,
        password_hash=password_hash,
        password_algo_params=algo_params or {"m": 65536, "t": 3, "p": 4},
        status=status,
        mfa_required=mfa_required,
        failed_login_count=failed_login_count,
        locked_until=locked_until,
        mfa_methods=mfa_methods,
    )
