"""PUT /users/{id}/roles: owner floor, RBAC, audit, notify (QA #1648 d2)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api.users import make_users_router
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot

OWNER = uuid.uuid4()
TARGET = uuid.uuid4()


class _Emitter:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def emit(self, action: str, **kw: Any) -> None:
        self.calls.append({"action": action, **kw})


class _Store:
    def __init__(self, roles: set[str], owners: int) -> None:
        self.roles = frozenset(roles)
        self.owners = owners

    async def get_roles(self, user_id: uuid.UUID) -> frozenset[str] | None:
        return self.roles

    async def count_active_owners(self) -> int:
        return self.owners

    async def set_roles(self, user_id: uuid.UUID, roles: frozenset[str]) -> None:
        self.roles = roles


class _Resolver:
    def __init__(self, snap: PrincipalSnapshot | None) -> None:
        self.snap = snap

    def resolve(self, request: Request) -> PrincipalSnapshot | None:
        return self.snap


class _Notifier:
    def __init__(self) -> None:
        self.users: list[uuid.UUID] = []

    async def roles_changed(self, user_id: uuid.UUID) -> None:
        self.users.append(user_id)


def _client(store: _Store, snap: PrincipalSnapshot | None, em: _Emitter, n: _Notifier):
    app = FastAPI()
    app.include_router(make_users_router(store, em, _Resolver(snap), n))
    return TestClient(app)


def _admin() -> PrincipalSnapshot:
    return PrincipalSnapshot(OWNER, frozenset({"owner"}), frozenset(Permission))


def _manager() -> PrincipalSnapshot:
    return PrincipalSnapshot(OWNER, frozenset({"manager"}), frozenset({Permission.ORDERS_READ}))


def test_put_roles_last_owner_demotion_is_rejected() -> None:
    store, em, n = _Store({"owner"}, 1), _Emitter(), _Notifier()
    r = _client(store, _admin(), em, n).put(f"/users/{TARGET}/roles", json={"roles": ["viewer"]})
    assert r.status_code == 409
    assert store.roles == {"owner"}
    assert n.users == []


def test_put_roles_owner_demotion_allowed_when_another_owner_exists() -> None:
    store, em, n = _Store({"owner"}, 2), _Emitter(), _Notifier()
    r = _client(store, _admin(), em, n).put(f"/users/{TARGET}/roles", json={"roles": ["viewer"]})
    assert r.status_code == 200
    assert store.roles == {"viewer"}
    assert n.users == [TARGET]
    assert {c["action"] for c in em.calls} == {"roles.grant", "roles.revoke"}


def test_put_roles_manager_forbidden_and_denial_audited() -> None:
    store, em, n = _Store({"viewer"}, 1), _Emitter(), _Notifier()
    r = _client(store, _manager(), em, n).put(f"/users/{TARGET}/roles", json={"roles": ["owner"]})
    assert r.status_code == 403
    assert em.calls[0]["action"] == "rbac.denied"
    assert store.roles == {"viewer"}


def test_put_roles_unauthenticated_is_401_and_unwired_is_501() -> None:
    em, n = _Emitter(), _Notifier()
    assert (
        _client(_Store({"viewer"}, 1), None, em, n)
        .put(f"/users/{TARGET}/roles", json={"roles": ["viewer"]})
        .status_code
        == 401
    )
    app = FastAPI()
    app.include_router(make_users_router(None, em))
    assert TestClient(app).put(f"/users/{TARGET}/roles", json={"roles": ["x"]}).status_code == 501


def test_put_roles_rejects_unknown_role() -> None:
    r = _client(_Store({"viewer"}, 1), _admin(), _Emitter(), _Notifier()).put(
        f"/users/{TARGET}/roles", json={"roles": ["root"]}
    )
    assert r.status_code == 400
