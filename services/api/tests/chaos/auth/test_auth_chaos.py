"""E09-Q05 auth chaos (C-13.6 scenarios: 2 Postgres loss, 9 clock skew; ticket scenarios 3-5
exercise the WS revocation / session-store paths in-process).

Wall-clock rule (T14): every time-dependent assert uses an injected clock or a fixed `unix_time`;
no sleeps and no real-time budgets here (latency budgets live in tests/load/k6/auth.js).
"""

from __future__ import annotations

import asyncio
import os
import shutil
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from candleviewer.auth.errors import SessionNotFound, SessionRevoked
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.session_service import SessionService
from candleviewer.auth.totp import TOTP_STEP_SECONDS, generate_code, time_step_for, verify_code
from candleviewer.ws.revocation import RevocationHub
from tests.unit.auth.session_fakes import FakeSessionRepository

pytestmark = [pytest.mark.chaos, pytest.mark.integration]
_NOW = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)


def _service(repo: Any) -> SessionService:
    return SessionService(repo, Hasher(pepper=os.urandom(16).hex()), clock=lambda: _NOW)


class _DownableRepo(FakeSessionRepository):
    """Session store whose backing Postgres can be 'restarted' (all calls raise while down)."""

    down = False

    async def find_by_id(self, session_id: str) -> Any:
        if self.down:
            raise ConnectionError("postgres unavailable")
        return await super().find_by_id(session_id)


async def test_s1_postgres_restart_fails_closed_then_recovers() -> None:
    # Scenario 2 (C-13.6). Needs only the fake store; the docker variant is below.
    repo = _DownableRepo()
    svc = _service(repo)
    minted = await svc.mint(str(uuid.uuid4()))
    sid = str(minted.session_id)
    assert (await svc.require_active(sid)).id is not None
    repo.down = True
    with pytest.raises(ConnectionError):  # fail closed: an error, never a granted session
        await svc.require_active(sid)
    repo.down = False
    assert (await svc.require_active(sid)).id is not None  # recovers with no manual step


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker stack unavailable")
async def test_s1b_postgres_restart_against_compose_stack() -> None:
    from tests.chaos.storage._stack import compose

    await compose("restart", "postgres")  # bounded by _stack's timeout; real fault injection


def test_s2_clock_skew_pm1_accepted_pm3_rejected() -> None:
    # Scenario 9 (C-13.6) / SR-021: +-1 step accepted, +-3 rejected.
    secret = os.urandom(20)
    server_t = 1_800_000_000.0
    step = time_step_for(server_t)
    for k in (-1, 1):
        code = generate_code(secret, step + k)
        assert verify_code(secret, code, unix_time=server_t) == step + k
    for k in (-3, 3):
        code = generate_code(secret, step + k)
        assert verify_code(secret, code, unix_time=server_t) is None
    assert TOTP_STEP_SECONDS == 30


class _Sock:
    def __init__(self) -> None:
        self.frames: list[tuple[dict[str, Any], int]] = []

    async def close(self, bye: dict[str, Any], code: int) -> None:
        self.frames.append((bye, code))


async def test_s3_ws_restart_new_gateway_has_no_pre_restart_authorisation() -> None:
    repo = FakeSessionRepository()
    svc = _service(repo)
    sid = str((await svc.mint(str(uuid.uuid4()))).session_id)
    old_hub = RevocationHub()
    sock = _Sock()
    old_hub.register(sid, sock.close)
    new_hub = RevocationHub()  # restart: registry is empty, state is not carried over
    assert await new_hub.revoke(sid) == 0
    assert old_hub is not new_hub and not sock.frames
    await svc.revoke(sid, reason="logout")  # reconnect must re-check the session store
    with pytest.raises(SessionRevoked):
        await svc.require_active(sid)


async def test_s4_revocation_storm_every_socket_gets_bye_4401() -> None:
    svc = _service(FakeSessionRepository())
    hub = RevocationHub()
    socks: dict[str, list[_Sock]] = {}
    for _ in range(50):  # 50 managers, 2 sockets each
        sid = str((await svc.mint(str(uuid.uuid4()))).session_id)
        socks[sid] = [_Sock(), _Sock()]
        for s in socks[sid]:
            hub.register(sid, s.close)
    closed = await asyncio.gather(*(hub.revoke(sid) for sid in socks))
    assert sum(closed) == 100
    for ss in socks.values():
        for s in ss:
            assert s.frames and s.frames[0][1] == 4401 and s.frames[0][0]["t"] == "bye"
    assert await asyncio.gather(*(hub.revoke(sid) for sid in socks)) == [0] * 50  # none survive


async def test_s5_session_store_pressure_sweep_does_not_block_auth() -> None:
    repo = FakeSessionRepository()
    svc = _service(repo)
    user = str(uuid.uuid4())
    sids = [str((await svc.mint(user)).session_id) for _ in range(500)]
    probe = sids[0]

    async def sweeper() -> None:
        for sid in sids[1:]:
            await svc.revoke(sid, reason="expired")
            await asyncio.sleep(0)

    sweep = asyncio.create_task(sweeper())
    for _ in range(50):  # auth keeps succeeding while the sweep runs
        assert (await svc.require_active(probe)).id is not None
        await asyncio.sleep(0)
    await sweep
    assert len(await svc.list_sessions(user)) == 1
    with pytest.raises((SessionNotFound, SessionRevoked)):
        await svc.require_active(sids[1])
