"""InviteService (E09-S05): single-use, expiry, role immutability, abandoned enrolment."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from candleviewer.auth.errors import (
    InviteConflict,
    InviteNotFound,
    InviteRejected,
    MfaCodeInvalid,
    PasswordPolicyViolation,
)
from candleviewer.auth.invite_service import (
    ENROLL_WINDOW,
    INVITE_TTL,
    InviteService,
    check_password_policy,
    hash_token,
)
from candleviewer.auth.models import (
    EnrollmentStart,
    InviteCreateRequest,
    InviteRecord,
    UserStatus,
)

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
GOOD_PW = "correct horse battery"


class FakeRepo:
    def __init__(self) -> None:
        self.rows: dict[str, InviteRecord] = {}
        self.emails: set[str] = set()

    async def create_user_with_invite(self, **kw: Any) -> bool:
        if kw["email"] in self.emails:
            return False
        self.emails.add(kw["email"])
        self.rows[kw["token_hash"]] = InviteRecord(
            id=kw["invite_id"],
            user_id=kw["user_id"],
            role=kw["role"],
            username=kw["username"],
            email=kw["email"],
            display_name=kw["display_name"],
            expires_at=kw["expires_at"],
            created_at=T0,
        )
        return True

    async def find_by_token_hash(self, token_hash: str) -> InviteRecord | None:
        return self.rows.get(token_hash)

    async def consume(
        self, token_hash: str, *, now: datetime, pending_password_hash: str
    ) -> InviteRecord | None:
        row = self.rows.get(token_hash)
        if row is None or row.consumed_at or row.revoked_at or row.expires_at <= now:
            return None
        new = row.model_copy(
            update={"consumed_at": now, "pending_password_hash": pending_password_hash}
        )
        self.rows[token_hash] = new
        return new

    async def find_consumed_for_user(self, user_id: uuid.UUID) -> InviteRecord | None:
        return None

    async def activate_user(self, user_id: uuid.UUID, **kw: Any) -> bool:
        for h, r in self.rows.items():
            if r.user_id == user_id and r.user_status is UserStatus.INVITED:
                self.rows[h] = r.model_copy(update={"user_status": UserStatus.ACTIVE})
                return True
        return False

    async def reissue(self, user_id: uuid.UUID, **kw: Any) -> InviteRecord | None:
        return None

    async def revoke_open(self, user_id: uuid.UUID, *, now: datetime) -> bool:
        hit = False
        for h, r in list(self.rows.items()):
            if r.user_id == user_id and not r.consumed_at and not r.revoked_at:
                self.rows[h] = r.model_copy(update={"revoked_at": now})
                hit = True
        return hit

    async def list_pending(self, *, now: datetime) -> tuple[InviteRecord, ...]:
        return tuple(r for r in self.rows.values() if not r.consumed_at and not r.revoked_at)


class FakeHasher:
    async def hash(self, password: str, params: Any) -> str:
        return "$argon2id$fake$" + password[:2]


class FakeMfa:
    async def enroll(self, user_id: str, request: Any, *, account_name: str) -> Any:
        return EnrollmentStart(
            method_id=uuid.uuid4(), otpauth_uri="otpauth://x", secret_base32="AAAA"
        )

    async def confirm_enrollment(
        self, user_id: str, *, method_id: str, code: str
    ) -> tuple[Any, tuple[str, ...]]:
        if code != "123456":
            raise MfaCodeInvalid("bad")
        return "totp", ("rc-1", "rc-2")


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


def _make() -> tuple[InviteService, FakeRepo, Clock]:
    repo, clock = FakeRepo(), Clock()
    svc = InviteService(repo, FakeHasher(), FakeMfa(), clock=clock)  # type: ignore[arg-type]  # fakes
    return svc, repo, clock


def _req(email: str = "ann@example.com", role: str = "viewer") -> InviteCreateRequest:
    return InviteCreateRequest.model_validate(
        {"email": email, "username": "annie", "roles": [role]}
    )


async def test_create_returns_high_entropy_token_stored_only_as_hash() -> None:
    svc, repo, _ = _make()
    inv = await svc.create(_req(), invited_by=uuid.uuid4())
    assert len(inv.token) >= 43
    assert inv.token not in repo.rows
    assert hash_token(inv.token) in repo.rows
    assert inv.expires_at == T0 + INVITE_TTL


async def test_create_duplicate_email_conflicts() -> None:
    svc, _, _ = _make()
    await svc.create(_req(), invited_by=uuid.uuid4())
    with pytest.raises(InviteConflict):
        await svc.create(_req(), invited_by=uuid.uuid4())


def test_owner_role_cannot_be_invited() -> None:
    with pytest.raises(ValueError):
        _req(role="owner")


async def test_invite_accepted_end_to_end_activates_user() -> None:
    svc, _, _ = _make()
    inv = await svc.create(_req(), invited_by=uuid.uuid4())
    await svc.begin_redemption(inv.token, password=GOOD_PW, source_ip="1.1.1.1")
    rec, codes = await svc.complete_redemption(
        inv.token, method_id="m", code="123456", source_ip="1.1.1.1"
    )
    assert rec.role == "viewer" and codes == ("rc-1", "rc-2")


async def test_expired_token_rejected_after_72h() -> None:
    svc, _, clock = _make()
    inv = await svc.create(_req(), invited_by=uuid.uuid4())
    clock.now = T0 + INVITE_TTL
    with pytest.raises(InviteRejected) as e:
        await svc.inspect(inv.token, source_ip="1.1.1.1")
    assert e.value.reason == "expired"


async def test_token_reuse_rejected() -> None:
    svc, _, _ = _make()
    inv = await svc.create(_req(), invited_by=uuid.uuid4())
    await svc.begin_redemption(inv.token, password=GOOD_PW, source_ip="1.1.1.1")
    with pytest.raises(InviteRejected) as e:
        await svc.begin_redemption(inv.token, password=GOOD_PW, source_ip="1.1.1.1")
    assert e.value.reason == "redeemed"


async def test_unknown_token_rejected() -> None:
    svc, _, _ = _make()
    with pytest.raises(InviteRejected) as e:
        await svc.inspect("x" * 40, source_ip="1.1.1.1")
    assert e.value.reason == "unknown"


async def test_abandoned_enrolment_leaves_user_invited() -> None:
    svc, repo, clock = _make()
    inv = await svc.create(_req(), invited_by=uuid.uuid4())
    await svc.begin_redemption(inv.token, password=GOOD_PW, source_ip="1.1.1.1")
    clock.now = T0 + ENROLL_WINDOW + timedelta(seconds=1)
    with pytest.raises(InviteRejected):
        await svc.complete_redemption(inv.token, method_id="m", code="123456", source_ip="1.1.1.1")
    assert repo.rows[hash_token(inv.token)].user_status is UserStatus.INVITED


async def test_wrong_totp_code_does_not_activate() -> None:
    svc, repo, _ = _make()
    inv = await svc.create(_req(), invited_by=uuid.uuid4())
    await svc.begin_redemption(inv.token, password=GOOD_PW, source_ip="1.1.1.1")
    with pytest.raises(InviteRejected) as e:
        await svc.complete_redemption(inv.token, method_id="m", code="000000", source_ip="1.1.1.1")
    assert e.value.reason == "enrollment_invalid"
    assert repo.rows[hash_token(inv.token)].user_status is UserStatus.INVITED


async def test_concurrent_redemptions_exactly_one_wins() -> None:
    svc, _, _ = _make()
    inv = await svc.create(_req(), invited_by=uuid.uuid4())
    res = await asyncio.gather(
        *(svc.begin_redemption(inv.token, password=GOOD_PW, source_ip="1.1.1.1") for _ in range(2)),
        return_exceptions=True,
    )
    assert sum(isinstance(r, EnrollmentStart) for r in res) == 1
    assert sum(isinstance(r, InviteRejected) for r in res) == 1


async def test_revoked_token_rejected_and_revoke_unknown_not_found() -> None:
    svc, _, _ = _make()
    inv = await svc.create(_req(), invited_by=uuid.uuid4())
    await svc.revoke(inv.user_id)
    with pytest.raises(InviteRejected) as e:
        await svc.inspect(inv.token, source_ip="1.1.1.1")
    assert e.value.reason == "revoked"
    with pytest.raises(InviteNotFound):
        await svc.revoke(uuid.uuid4())


async def test_repeated_rejections_trip_ip_throttle() -> None:
    svc, _, _ = _make()
    for _ in range(10):
        with pytest.raises(InviteRejected):
            await svc.inspect("y" * 40, source_ip="9.9.9.9")
    assert svc.is_blocked("9.9.9.9")
    assert not svc.is_blocked("8.8.8.8")


@pytest.mark.parametrize("pw", ["short", "password1234", "aaaaaaaaaaaaaa", "annie-annie-annie"])
def test_password_policy_rejects_weak(pw: str) -> None:
    with pytest.raises(PasswordPolicyViolation):
        check_password_policy(pw, username="annie", email="ann@example.com")


def test_password_policy_accepts_good() -> None:
    check_password_policy(GOOD_PW, username="annie", email="ann@example.com")
