"""E09-X04 SR-029 automated counterpart of the disable-user drill (in-process, no network).

The `DELETE /users/{userId}` disable cascade is owned by E42-T04 (#965) and does not exist yet,
so this test drives the same primitives that cascade must call, through the real
`create_app()` wiring: `SessionService.revoke_all` and the app's own `RevocationHub`. It is a
regression guard for the propagation path, not the staging drill (which a human still runs).

Measured on the injected clock: revocation is stamped at the action instant (zero injected-time
delay, i.e. no timer/deferred path), and every effect is observed before the call returns.
"""

from __future__ import annotations

import os
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from candleviewer.app import create_app
from candleviewer.auth.envelope import TotpEncryptor
from candleviewer.auth.errors import SessionNotFound, SessionRevoked
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.auth.session_service import SessionService
from candleviewer.auth.step_up import StepUpService
from candleviewer.ws.revocation import CLOSE_TOKEN_EXPIRED, RevocationHub
from tests.unit.auth.mfa_fakes import FakeMfaRepository
from tests.unit.auth.session_fakes import FakeSessionRepository

_T0 = datetime(2026, 10, 9, 12, 0, 0, tzinfo=UTC)
#: SR-029 says "immediately"; E42-T04 states the product bound as 5 s.
_SR029_BOUND_S = 5.0


class _Clock:
    def __init__(self) -> None:
        self.now = _T0
        self.reads = 0

    def __call__(self) -> datetime:
        self.reads += 1
        return self.now


async def _snapshot(uid: uuid.UUID) -> PrincipalSnapshot:
    return PrincipalSnapshot(uid, frozenset({"manager"}), frozenset({Permission.MARKETDATA_READ}))


class _Env:
    def __init__(self) -> None:
        self.clock = _Clock()
        self.repo = FakeSessionRepository()
        self.app = create_app(snapshot_loader=_snapshot, auth_clock=self.clock)
        auth: Any = self.app.state.app_context.auth
        self.sessions = SessionService(
            self.repo, Hasher(pepper=os.urandom(16).hex()), clock=self.clock
        )
        self.step_up = StepUpService(
            FakeMfaRepository(), self.repo, TotpEncryptor(os.urandom(32)), clock=self.clock
        )
        # The composition root wires these only with a real database; same seams, fake storage.
        auth._sessions = self.sessions
        auth._step_up = self.step_up
        self.audit: list[dict[str, Any]] = []
        self.app.state.app_context.audit._writer = self  # stand-in for the started AuditWriter
        self.hub: RevocationHub = self.app.state.revocation_hub
        self.client = TestClient(self.app, client=("127.0.0.1", 50000))

    async def emit(self, action: str, **kw: Any) -> None:
        self.audit.append({"action": action, **kw})

    def run(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        assert self.client.portal is not None
        return self.client.portal.call(lambda: fn(*args, **kwargs))

    async def disable(self, user_id: str) -> int:
        """What SR-029 requires of the cascade: revoke every session, then close every socket."""
        revoked = await self.sessions.revoke_all(user_id, reason="user_disabled")
        closed = 0
        for record in revoked:
            closed += await self.hub.revoke(str(record.id), "user_disabled")
        return closed


@pytest.fixture
def env() -> Any:
    e = _Env()
    with e.client:
        yield e
        e.run(e.step_up.stop)


def _auth_ws(ws: Any, token: str) -> dict[str, Any]:
    ws.send_json({"t": "auth", "id": "a", "p": {"access_token": token}})
    out: dict[str, Any] = ws.receive_json()
    return out


def test_disable_user_drill_terminates_sessions_sockets_and_pending_actions(env: Any) -> None:
    user = str(uuid.uuid4())
    other = str(uuid.uuid4())
    a = env.run(env.sessions.mint, user)
    b = env.run(env.sessions.mint, user)
    bystander = env.run(env.sessions.mint, other)
    # Pending activity: a step-up challenge recorded against the live session.
    env.run(env.step_up.record_pending, str(a.session_id), "users")
    assert env.run(env.step_up.pending_action_class, str(a.session_id)) == "users"

    with env.client.websocket_connect("/ws") as ws:
        ok = _auth_ws(ws, a.access_token)
        assert ok["t"] == "auth_ok"
        ws.send_json({"t": "sub", "id": "s", "p": {"topics": [{"ch": "book.BTCUSDT.50"}]}})
        assert ws.receive_json()["p"]["results"][0]["ok"] is True

        action_at = env.clock.now
        wall = time.perf_counter()
        closed = env.run(env.disable, user)
        wall_s = time.perf_counter() - wall

        bye = ws.receive_json()
        assert bye["t"] == "bye"
        assert bye["p"]["code"] == CLOSE_TOKEN_EXPIRED
        assert bye["p"]["reason"] == "user_disabled"
        assert bye["p"]["reconnect"] is False
    assert closed == 1

    # Sessions terminated, stamped at the action instant on the injected clock.
    for minted in (a, b):
        rec = env.repo.sessions[str(minted.session_id)]
        assert rec.revoked_at is not None
        assert (rec.revoked_at - action_at).total_seconds() == 0.0
        assert rec.revoked_reason == "user_disabled"
        with pytest.raises((SessionRevoked, SessionNotFound)):
            env.run(env.sessions.authenticate_access_token, minted.access_token)
    # Pending activity cancelled: the challenge is gone and cannot be completed.
    assert env.run(env.step_up.pending_action_class, str(a.session_id)) is None
    # Blast radius: another user's session is untouched.
    assert env.repo.sessions[str(bystander.session_id)].revoked_at is None
    # Wall-clock sanity bound only (in-process); the staging drill records the real figure.
    assert wall_s < _SR029_BOUND_S
    print(f"SR-029 drill: injected-clock delay=0.000s wall={wall_s * 1000:.2f}ms sockets={closed}")


def test_disable_user_drill_revoked_token_cannot_reopen_a_socket(env: Any) -> None:
    user = str(uuid.uuid4())
    minted = env.run(env.sessions.mint, user)
    env.run(env.disable, user)
    with env.client.websocket_connect("/ws") as ws:
        bye = _auth_ws(ws, minted.access_token)
        assert (bye["t"], bye["p"]["reason"]) == ("bye", "auth_failed")


def test_disable_user_drill_is_idempotent(env: Any) -> None:
    user = str(uuid.uuid4())
    env.run(env.sessions.mint, user)
    env.run(env.disable, user)
    assert env.run(env.disable, user) == 0
