"""Unit tests for `StepUpService` (E09-S04); names map to Gherkin scenarios."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from candleviewer.auth.envelope import TotpEncryptor
from candleviewer.auth.errors import (
    SessionReadOnly,
    StepUpCodeInvalid,
    StepUpRequired,
    UnknownActionClass,
)
from candleviewer.auth.mfa_service import MfaService
from candleviewer.auth.models import MfaEnrollRequest, MfaMethodKind, SessionRecord
from candleviewer.auth.step_up import StepUpService
from candleviewer.auth.totp import generate_code, time_step_for

from .mfa_fakes import FakeMfaRepository
from .session_fakes import FakeSessionRepository

_RC_KEY = b"k" * 32
_T0 = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)


class _Clock:
    def __init__(self) -> None:
        self.now = _T0

    def __call__(self) -> datetime:
        return self.now


class _Positions:
    def __init__(self, count: int) -> None:
        self.count = count

    async def open_position_count(self, user_id: str) -> int:
        return self.count


async def _setup() -> tuple[StepUpService, _Clock, bytes, uuid.UUID, FakeSessionRepository]:
    clock = _Clock()
    repo = FakeMfaRepository()
    enc = TotpEncryptor(os.urandom(32))
    mfa = MfaService(repo, enc, recovery_code_key=_RC_KEY, clock=clock)
    user = uuid.uuid4()
    res = await mfa.enroll(
        str(user), MfaEnrollRequest(method=MfaMethodKind.TOTP, label=""), account_name="o"
    )
    seed = enc.decrypt(repo.methods[str(res.method_id)].secret_enc)  # type: ignore[arg-type]
    code = generate_code(seed, time_step_for(_T0.timestamp()) - 1)
    await mfa.confirm_enrollment(str(user), method_id=str(res.method_id), code=code)
    sessions = FakeSessionRepository()
    return StepUpService(repo, sessions, enc, clock=clock), clock, seed, user, sessions


def _code(seed: bytes, clock: _Clock) -> str:
    return generate_code(seed, time_step_for(clock.now.timestamp()))


async def test_dangerous_action_requires_step_up() -> None:
    svc, *_ = await _setup()
    with pytest.raises(StepUpRequired):
        svc.require_elevation("s1", "keys")


async def test_grace_window_within_action_class() -> None:
    svc, clock, seed, user, _ = await _setup()
    await svc.step_up(str(user), "s1", "keys", _code(seed, clock))
    clock.now += timedelta(minutes=3)
    svc.require_elevation("s1", "keys")
    assert svc.remaining_grace("s1", "keys") == timedelta(minutes=2)
    with pytest.raises(StepUpRequired):  # other class gets no grace
        svc.require_elevation("s1", "users")
    clock.now += timedelta(minutes=3)
    with pytest.raises(StepUpRequired):
        svc.require_elevation("s1", "keys")


@pytest.mark.parametrize("cls", ["live_enablement", "killswitch"])
async def test_grace_never_applies_to_no_grace_classes(cls: str) -> None:
    svc, clock, seed, user, _ = await _setup()
    await svc.step_up(str(user), "s1", "keys", _code(seed, clock))
    with pytest.raises(StepUpRequired):
        svc.require_elevation("s1", cls)
    clock.now += timedelta(minutes=1)
    grant = await svc.step_up(str(user), "s1", cls, _code(seed, clock))
    assert grant.single_use
    with pytest.raises(StepUpRequired):
        svc.require_elevation("s1", cls)


async def test_three_failures_downgrade_to_readonly_for_five_minutes() -> None:
    svc, clock, seed, user, _ = await _setup()
    await svc.step_up(str(user), "s1", "keys", _code(seed, clock))
    with pytest.raises(StepUpCodeInvalid) as e1:
        await svc.step_up(str(user), "s1", "keys", "000000")
    assert e1.value.failures_remaining == 2
    with pytest.raises(StepUpCodeInvalid):
        await svc.step_up(str(user), "s1", "keys", "000000")
    with pytest.raises(SessionReadOnly):
        await svc.step_up(str(user), "s1", "keys", "000000")
    with pytest.raises(SessionReadOnly):
        svc.assert_writable("s1")
    with pytest.raises(SessionReadOnly):  # elevation wiped by the downgrade
        svc.require_elevation("s1", "keys")
    clock.now += timedelta(minutes=5)
    svc.assert_writable("s1")


async def test_replayed_code_is_rejected() -> None:
    svc, clock, seed, user, _ = await _setup()
    code = _code(seed, clock)
    await svc.step_up(str(user), "s1", "keys", code)
    with pytest.raises(StepUpCodeInvalid):
        await svc.step_up(str(user), "s2", "keys", code)


async def test_elevation_is_bound_to_session_id() -> None:
    svc, clock, seed, user, _ = await _setup()
    await svc.step_up(str(user), "s1", "keys", _code(seed, clock))
    with pytest.raises(StepUpRequired):
        svc.require_elevation("s2", "keys")


async def test_unknown_action_class_rejected() -> None:
    svc, clock, seed, user, _ = await _setup()
    with pytest.raises(UnknownActionClass):
        await svc.step_up(str(user), "s1", "bogus", _code(seed, clock))
    with pytest.raises(StepUpRequired):
        svc.require_elevation("s1", "bogus")


def _session(user: uuid.UUID) -> SessionRecord:
    return SessionRecord(
        id=uuid.uuid4(),
        user_id=user,
        refresh_token_hash=uuid.uuid4().hex,
        access_token_jti=None,
        issued_at=_T0,
        last_seen_at=_T0,
        expires_at=_T0 + timedelta(hours=12),
        revoked_at=None,
        revoked_reason=None,
        ip=None,
        user_agent=None,
        device_label=None,
        is_electron=False,
        mfa_satisfied_at=_T0,
    )


async def test_owner_reset_revokes_sessions_without_oms_effects_or_secret() -> None:
    svc, clock, seed, owner, sessions = await _setup()
    target = uuid.uuid4()
    s = _session(target)
    await sessions.create_session(s)
    positions = _Positions(3)
    preview = await svc.preview_reset(str(target), positions)
    assert preview.open_position_count == 3
    assert "NOT cancel" in preview.message
    with pytest.raises(StepUpRequired):  # reset itself needs fresh step-up
        await svc.reset_totp(
            actor_session_id="o1", actor_user_id=str(owner), target_user_id=str(target)
        )
    await svc.step_up(str(owner), "o1", "users", _code(seed, clock))
    result = await svc.reset_totp(
        actor_session_id="o1", actor_user_id=str(owner), target_user_id=str(target)
    )
    assert result.sessions_revoked == 1
    assert sessions.sessions[str(s.id)].revoked_at is not None
    assert not hasattr(result, "secret") and not hasattr(result, "recovery_codes")
    assert positions.count == 3  # read-only provider; no OMS mutation API exists


async def test_owner_cannot_reset_self() -> None:
    svc, clock, seed, owner, _ = await _setup()
    await svc.step_up(str(owner), "o1", "users", _code(seed, clock))
    with pytest.raises(StepUpRequired):
        await svc.reset_totp(
            actor_session_id="o1", actor_user_id=str(owner), target_user_id=str(owner)
        )
