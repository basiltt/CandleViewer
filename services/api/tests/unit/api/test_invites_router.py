"""HTTP-level E09-S05 tests through the real step-up middleware + invites router."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from fastapi import Request
from fastapi.testclient import TestClient

from candleviewer.api.invites import make_invites_router
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.invite_service import INVITE_TTL, InviteService
from candleviewer.auth.scopes import PrincipalSnapshot
from tests.unit.api.test_step_up_router import _H, _build, _code, _Emitter
from tests.unit.auth.test_invite_service import (
    GOOD_PW,
    FakeHasher,
    FakeMfa,
    FakeRepo,
)


class _InvAuth:
    invites_is_active = True

    def __init__(self, svc: InviteService) -> None:
        self.invites = svc


class _Resolver:
    def __init__(self, snap: PrincipalSnapshot) -> None:
        self.snap = snap

    def resolve(self, request: Request) -> PrincipalSnapshot | None:
        return self.snap if request.headers.get("authorization") else None


async def _setup(role: str = "owner") -> tuple[TestClient, _Emitter, Any, Any, FakeRepo, Any]:
    c, em, seed, clock, user = await _build()
    repo = FakeRepo()
    svc = InviteService(repo, FakeHasher(), FakeMfa(), clock=clock)  # type: ignore[arg-type]  # fakes
    snap = PrincipalSnapshot(
        user_id=user,
        roles=frozenset({role}),
        permissions=frozenset({Permission.USERS_WRITE}) if role == "owner" else frozenset(),
    )
    c.app.include_router(make_invites_router(_InvAuth(svc), em, _Resolver(snap)))  # type: ignore[attr-defined]
    return c, em, seed, clock, repo, svc


_BODY = {"email": "ann@example.com", "username": "annie", "roles": ["viewer"]}


def _elevate(c: TestClient, seed: bytes, clock: Any) -> None:
    c.post("/auth/step-up", headers=_H, json={"code": _code(seed, clock), "action_class": "users"})


async def test_create_user_requires_step_up_then_returns_link_once() -> None:
    c, em, seed, clock, _, _ = await _setup()
    r = c.post("/users", headers=_H, json=_BODY)
    assert r.status_code == 403 and r.json()["code"] == "step_up_required"
    _elevate(c, seed, clock)
    r = c.post("/users", headers=_H, json=_BODY)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "invited" and body["invite_url"].startswith("/invite/")
    assert "users.invited" in em.actions()
    pending = c.get("/users/invites", headers=_H).json()["items"]
    assert len(pending) == 1 and "invite_url" not in pending[0] and "token" not in pending[0]


async def test_non_owner_forbidden_on_create() -> None:
    c, _, seed, clock, repo, _ = await _setup(role="viewer")
    _elevate(c, seed, clock)
    r = c.post("/users", headers=_H, json=_BODY)
    assert r.status_code in (403,) and not repo.rows


async def test_create_rejects_owner_role_and_duplicate() -> None:
    c, _, seed, clock, _, _ = await _setup()
    _elevate(c, seed, clock)
    bad = {**_BODY, "roles": ["owner"]}
    assert c.post("/users", headers=_H, json=bad).status_code == 422
    assert c.post("/users", headers=_H, json=_BODY).status_code == 201
    assert c.post("/users", headers=_H, json=_BODY).status_code == 409


async def _invite(c: TestClient, seed: bytes, clock: Any) -> str:
    _elevate(c, seed, clock)
    url = c.post("/users", headers=_H, json=_BODY).json()["invite_url"]
    return url.rsplit("/", 1)[1]


async def test_invite_accepted_flow_over_http() -> None:
    c, em, seed, clock, _, _ = await _setup()
    tok = await _invite(c, seed, clock)
    assert c.get(f"/invites/{tok}").json()["role"] == "viewer"
    start = c.post(f"/invites/{tok}", json={"password": GOOD_PW})
    assert start.status_code == 200
    done = c.post(
        f"/invites/{tok}/confirm", json={"method_id": start.json()["method_id"], "code": "123456"}
    )
    assert done.status_code == 200 and done.json()["status"] == "active"
    assert done.json()["recovery_codes"] == ["rc-1", "rc-2"]
    assert "users.invite_redeemed" in em.actions()


async def test_reuse_is_uniform_404_and_audited_warning() -> None:
    c, em, seed, clock, _, _ = await _setup()
    tok = await _invite(c, seed, clock)
    assert c.post(f"/invites/{tok}", json={"password": GOOD_PW}).status_code == 200
    again = c.post(f"/invites/{tok}", json={"password": GOOD_PW})
    unknown = c.get("/invites/" + "z" * 40)
    assert again.status_code == unknown.status_code == 404
    assert again.json() == unknown.json()
    rej = [x for x in em.calls if x["action"] == "users.invite_rejected"]
    assert rej[0]["reason"] == "redeemed" and rej[0]["severity"].value == "warning"


async def test_expired_invite_is_404_after_72h() -> None:
    c, em, seed, clock, _, _ = await _setup()
    tok = await _invite(c, seed, clock)
    clock.now += INVITE_TTL + timedelta(seconds=1)
    assert c.get(f"/invites/{tok}").status_code == 404
    assert [x["reason"] for x in em.calls if x["action"] == "users.invite_rejected"] == ["expired"]


async def test_role_tamper_on_redeem_is_403_and_audited_without_consuming() -> None:
    c, em, seed, clock, _, _ = await _setup()
    tok = await _invite(c, seed, clock)
    r = c.post(f"/invites/{tok}", json={"password": GOOD_PW, "role": "owner"})
    assert r.status_code == 403
    rej = [x for x in em.calls if x["action"] == "users.invite_rejected"]
    assert rej and rej[-1]["reason"] == "role_tamper" and rej[-1]["severity"].value == "warning"
    assert c.post(f"/invites/{tok}", json={"password": GOOD_PW}).status_code == 200
    t2 = c.post(f"/invites/{tok}/confirm", json={"method_id": "m", "code": "1", "roles": ["owner"]})
    assert t2.status_code == 403


async def test_revoke_and_reissue_invalidate_old_link() -> None:
    c, _, seed, clock, _, _ = await _setup()
    tok = await _invite(c, seed, clock)
    uid = c.get("/users/invites", headers=_H).json()["items"][0]["user_id"]
    assert c.delete(f"/users/{uid}/invite", headers=_H).status_code == 200
    assert c.get(f"/invites/{tok}").status_code == 404
    assert c.delete(f"/users/{uuid.uuid4()}/invite", headers=_H).status_code == 404


async def test_brute_force_token_guessing_trips_429_even_for_valid_token() -> None:
    c, _, seed, clock, _, _ = await _setup()
    tok = await _invite(c, seed, clock)
    bad = "A" * 43
    codes = [c.get(f"/invites/{bad}").status_code for _ in range(10)]
    assert set(codes) == {404}
    assert c.get(f"/invites/{bad}").status_code == 429
    assert c.get(f"/invites/{tok}").status_code == 429
