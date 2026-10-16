"""`POST /auth/refresh` and the idle lock (#2300; contract info "Idle lock"): a refresh is
not activity, and a locked session refreshes again once unlocked."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from candleviewer.audit.models import AuditOutcome
from candleviewer.auth.models import RefreshOutcome

from ._world import (
    _IDLE_S,
    _T0,
    World,
    _bearer,
    _session,
    _unlock,
)


async def test_refresh_is_not_activity_and_carries_the_idle_deadline_over(w: World) -> None:
    minted = await w.mint(await w.add_user())
    w.clock.now += timedelta(seconds=200)
    r = await w.client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": minted.refresh_token},
        headers=_bearer(minted),
    )
    assert r.status_code == 200, r.text
    successor = r.json()["tokens"]["access_token"]
    info = await _session(w, {"Authorization": f"Bearer {successor}"})
    assert info.json()["session"]["idle_deadline"] == (_T0 + timedelta(seconds=_IDLE_S)).isoformat()


async def test_a_refresh_refused_while_locked_works_again_after_the_unlock(w: World) -> None:
    minted = await w.mint(await w.add_user())
    w.lock()
    refresh = {"refresh_token": minted.refresh_token}
    locked = await w.client.post("/api/v1/auth/refresh", json=refresh, headers=_bearer(minted))
    assert (locked.status_code, locked.json()["code"]) == (401, "session_idle_locked")
    assert (await _unlock(w, _bearer(minted))).status_code == 200
    again = await w.client.post("/api/v1/auth/refresh", json=refresh, headers=_bearer(minted))
    assert again.status_code == 200, again.text


async def test_a_refresh_locked_after_its_check_is_session_idle_locked_then_denied(
    w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The lock engaged after the route's pre-check (the window includes the awaited intent
    record), so `refresh()` refuses it: the answer is still `session_idle_locked`, never
    `refresh_token_invalid`, and a DENIED outcome record follows the intent; nothing rotates."""
    minted = await w.mint(await w.add_user())
    deadline = _T0 + timedelta(seconds=_IDLE_S)
    w.clock.now = deadline - timedelta(seconds=1)
    refresh = w.sessions.refresh

    async def deadline_passes(raw_refresh_token: str, **kwargs: Any) -> RefreshOutcome:
        w.clock.now = deadline  # after the pre-check and the intent record
        return await refresh(raw_refresh_token, **kwargs)

    monkeypatch.setattr(w.sessions, "refresh", deadline_passes)
    r = await w.client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": minted.refresh_token},
        headers=_bearer(minted),
    )
    assert (r.status_code, r.json()["code"]) == (401, "session_idle_locked")
    assert r.json()["idle_locked_at"] == deadline.isoformat()
    intent, refused = w.audit.writer.records
    assert (intent["action"], intent["outcome"]) == ("auth.session_refreshed", AuditOutcome.SUCCESS)
    assert (refused["action"], refused["outcome"], refused["reason"]) == (
        "auth.session_refreshed",
        AuditOutcome.DENIED,
        "idle_locked",
    )
    row = await w.row(minted)
    assert not row.is_revoked and row.is_idle_locked(now=w.clock.now)
