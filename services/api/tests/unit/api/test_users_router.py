"""PUT /users/{id}/roles: owner floor, RBAC, audit, notify (QA #1648 d2)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api.users import make_users_router
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.owner_floor import assert_owner_floor
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot

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

    async def apply_roles(self, user_id: uuid.UUID, roles: frozenset[str]) -> bool:
        assert_owner_floor(
            current_roles=self.roles, new_roles=roles, active_owner_count=self.owners
        )
        self.roles = roles
        return True


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
    app.include_router(make_users_router(None, em, None, n))
    assert TestClient(app).put(f"/users/{TARGET}/roles", json={"roles": ["x"]}).status_code == 501


def test_put_roles_rejects_unknown_role() -> None:
    r = _client(_Store({"viewer"}, 1), _admin(), _Emitter(), _Notifier()).put(
        f"/users/{TARGET}/roles", json={"roles": ["root"]}
    )
    assert r.status_code == 400


def test_put_roles_registry_pushes_permission_change_to_live_socket() -> None:
    import asyncio

    from candleviewer.ws.permissions import ConnectionAuthz, ConnectionRegistry

    viewer = PrincipalSnapshot(TARGET, frozenset({"viewer"}), frozenset({Permission.ORDERS_WRITE}))
    sent: list[dict[str, Any]] = []

    async def send(frame: dict[str, Any]) -> None:
        sent.append(frame)

    async def resolve(uid: uuid.UUID) -> PrincipalSnapshot:
        return PrincipalSnapshot(uid, frozenset({"viewer"}), frozenset())

    reg = ConnectionRegistry(resolve, lambda: 1)
    reg.register(ConnectionAuthz(viewer), send)
    asyncio.run(reg.roles_changed(TARGET))
    assert sent[0]["t"] == "permission_change"
    assert sent[0]["p"]["permissions"] == []


def test_put_roles_endpoint_enforces_owner_floor_even_if_store_does_not() -> None:
    """Contract: the endpoint guards the floor itself; a store that skips
    the check (e.g. a naive implementation) cannot demote the last owner."""

    class _NaiveStore(_Store):
        async def apply_roles(self, user_id: uuid.UUID, roles: frozenset[str]) -> bool:
            self.roles = roles
            return True

    store, em, n = _NaiveStore({"owner"}, 1), _Emitter(), _Notifier()
    r = _client(store, _admin(), em, n).put(f"/users/{TARGET}/roles", json={"roles": ["viewer"]})
    assert r.status_code == 409
    assert store.roles == {"owner"}
    assert n.users == []


def test_put_roles_conflict_is_audited_and_no_role_change_audit_on_failure() -> None:
    store, em, n = _Store({"owner"}, 1), _Emitter(), _Notifier()
    _client(store, _admin(), em, n).put(f"/users/{TARGET}/roles", json={"roles": ["viewer"]})
    actions = [c["action"] for c in em.calls]
    assert actions == ["rbac.denied"]
    assert "roles.grant" not in actions and "roles.revoke" not in actions


def test_put_roles_missing_user_writes_no_role_audit() -> None:
    class _Gone(_Store):
        async def apply_roles(self, user_id: uuid.UUID, roles: frozenset[str]) -> bool:
            return False

    em = _Emitter()
    r = _client(_Gone({"viewer"}, 1), _admin(), em, _Notifier()).put(
        f"/users/{TARGET}/roles", json={"roles": ["manager"]}
    )
    assert r.status_code == 404
    assert em.calls == []


def test_ws_gateway_hooks_auth_ok_sub_check_and_live_permission_change() -> None:
    import asyncio

    from candleviewer.ws.permissions import (
        ConnectionRegistry,
        close_connection,
        handle_sub,
        open_connection,
    )

    viewer = PrincipalSnapshot(TARGET, frozenset({"viewer"}), frozenset({Permission.ORDERS_READ}))
    sent: list[dict[str, Any]] = []

    async def send(frame: dict[str, Any]) -> None:
        sent.append(frame)

    async def resolve(uid: uuid.UUID) -> PrincipalSnapshot:
        return PrincipalSnapshot(uid, frozenset({"viewer"}), frozenset())

    async def scenario() -> None:
        reg = ConnectionRegistry(resolve, lambda: 1)
        authz = await open_connection(reg, viewer, send)
        assert sent[0]["t"] == "auth_ok" and sent[0]["p"]["permissions"] == ["orders:read"]
        acc = str(uuid.uuid4())
        orders = {"ch": "orders", "opts": {"exchange_account_ids": [acc]}}
        viewer_grants = PrincipalSnapshot(
            TARGET,
            frozenset({"viewer"}),
            frozenset({Permission.ORDERS_READ}),
            (AccountGrant(uuid.UUID(acc), True, False, False),),
        )
        authz.principal = viewer_grants
        await handle_sub(authz, {"id": "s", "p": {"topics": [orders, {"ch": "bars.X"}]}}, send)
        res = sent[-1]["p"]["results"]
        assert [(r["ch"], r["ok"]) for r in res] == [("orders", True), ("bars.X", False)]
        sent.clear()
        store = _Store({"viewer"}, 2)
        app = FastAPI()
        app.include_router(make_users_router(store, _Emitter(), _Resolver(_admin()), reg))
        await reg.roles_changed(TARGET)
        assert [f["t"] for f in sent] == ["permission_change", "revoked"]
        close_connection(reg, authz)
        sent.clear()
        await reg.roles_changed(TARGET)
        assert sent == []

    asyncio.run(scenario())


def test_make_users_router_requires_audit_emitter_and_notifier() -> None:
    import pytest

    with pytest.raises(TypeError, match="required"):
        make_users_router(None, None, None, _Notifier())  # type: ignore[arg-type]  # the point
    with pytest.raises(TypeError, match="required"):
        make_users_router(None, _Emitter(), None, None)  # type: ignore[arg-type]  # the point
