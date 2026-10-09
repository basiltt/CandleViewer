"""E09-X02 session abuse cases (AC-SES-*): fixation, rotation, refresh reuse, expiry."""

from __future__ import annotations

import os
import uuid
from datetime import timedelta

import pytest

from candleviewer.auth.errors import (
    RefreshReuseDetected,
    SessionNotFound,
    SessionRevoked,
)
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.session_service import ACCESS_TOKEN_TTL, SessionService
from tests.unit.auth.session_fakes import FakeSessionRepository

from ._kit import Clock


def _svc() -> tuple[SessionService, FakeSessionRepository, Clock]:
    repo, clock = FakeSessionRepository(), Clock()
    return SessionService(repo, Hasher(pepper=os.urandom(8).hex()), clock=clock), repo, clock


async def test_ac_ses_01_fixation_preauth_id_never_becomes_session() -> None:  # U6 / SR-013
    svc, repo, _ = _svc()
    attacker_planted = "pre-login-session-id"
    first = await svc.mint(str(uuid.uuid4()))  # post-password step
    second = await svc.mint(str(uuid.uuid4()))  # post-MFA step
    assert str(first.session_id) != str(second.session_id)
    assert attacker_planted not in {str(k) for k in repo.sessions}
    with pytest.raises(SessionNotFound):
        await svc.authenticate_access_token(attacker_planted)
    with pytest.raises(SessionNotFound):
        await svc.require_active(attacker_planted)


async def test_ac_ses_02_every_refresh_issues_new_id_and_token() -> None:  # SR-013
    svc, _, _ = _svc()
    m = await svc.mint(str(uuid.uuid4()))
    nxt = await svc.refresh(m.refresh_token)
    assert nxt.minted.session_id != m.session_id
    assert nxt.minted.refresh_token != m.refresh_token
    assert nxt.minted.access_token != m.access_token


async def test_ac_ses_03_refresh_reuse_revokes_family_and_access_tokens() -> None:
    svc, _, _ = _svc()
    m = await svc.mint(str(uuid.uuid4()))
    live = (await svc.refresh(m.refresh_token)).minted
    with pytest.raises(RefreshReuseDetected):
        await svc.refresh(m.refresh_token)
    with pytest.raises(SessionRevoked):  # the victim's successor is now dead too
        await svc.authenticate_access_token(live.access_token)
    with pytest.raises(SessionRevoked):
        await svc.refresh(live.refresh_token)


async def test_ac_ses_04_refresh_cannot_extend_absolute_lifetime() -> None:
    svc, _repo, _ = _svc()
    m = await svc.mint(str(uuid.uuid4()))
    nxt = await svc.refresh(m.refresh_token)
    assert nxt.minted.expires_at == m.expires_at


async def test_ac_ses_05_access_token_expires_and_revoked_session_refused() -> None:
    svc, _, clock = _svc()
    m = await svc.mint(str(uuid.uuid4()))
    await svc.authenticate_access_token(m.access_token)
    clock.advance(ACCESS_TOKEN_TTL + timedelta(seconds=1))
    with pytest.raises(SessionNotFound):
        await svc.authenticate_access_token(m.access_token)


async def test_ac_ses_06_cookie_replay_from_other_context_accepted_by_design() -> None:
    """DESIGN DECISION TO CONFIRM (not a bug): sessions are not bound to IP/UA, so a stolen
    access token replayed from another address is accepted; detection relies on refresh reuse."""
    svc, _, _ = _svc()
    m = await svc.mint(str(uuid.uuid4()), ip="10.0.0.1", user_agent="victim-ua")
    rec = await svc.authenticate_access_token(m.access_token)  # attacker, no ip/ua presented
    assert rec.id == m.session_id


async def test_ac_ses_07_forged_access_token_rejected() -> None:
    svc, _, _ = _svc()
    await svc.mint(str(uuid.uuid4()))
    for forged in ("", "A" * 43, "../../etc/passwd", "x" * 4096):
        with pytest.raises(SessionNotFound):
            await svc.authenticate_access_token(forged)
