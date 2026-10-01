"""WS auth_ok permissions, per-subscribe check, mid-connection downgrade (QA #1648 d1)."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, Allow, Deny, DenyReason, PrincipalSnapshot
from candleviewer.ws.permissions import (
    ConnectionAuthz,
    ConnectionRegistry,
    auth_ok_payload,
    check_subscribe,
    handle_sub,
)

ACC = uuid.uuid4()
ALL = frozenset(Permission)
MGR = frozenset({Permission.MARKETDATA_READ, Permission.ORDERS_READ, Permission.ORDERS_WRITE})
VIEWER = frozenset({Permission.MARKETDATA_READ, Permission.ORDERS_READ})


def _snap(role: str, perms: frozenset[Permission]) -> PrincipalSnapshot:
    return PrincipalSnapshot(
        uuid.UUID(int=1), frozenset({role}), perms, (AccountGrant(ACC, True, True, False),)
    )


def test_auth_ok_payload_carries_roles_permissions_and_scope() -> None:
    p = auth_ok_payload(_snap("manager", MGR))
    assert p["roles"] == ["manager"]
    assert "orders:write" in p["permissions"]
    assert p["account_scope"] == [str(ACC)]


def test_subscribe_checked_per_topic() -> None:
    s = _snap("viewer", frozenset({Permission.MARKETDATA_READ}))
    assert isinstance(check_subscribe(s, "book.BTCUSDT"), Allow)
    assert isinstance(check_subscribe(s, "orders"), Deny)
    assert isinstance(check_subscribe(s, "bogus.X"), Deny)
    assert check_subscribe(s, "system") is None


def test_downgrade_pushes_frame_revokes_and_refuses_orders() -> None:
    conn = ConnectionAuthz(_snap("manager", MGR))
    conn.subscribe("book.BTCUSDT")
    conn.subscribe("orders", exchange_account_id=ACC)
    assert conn.may_submit_order()
    frames = conn.apply_snapshot(_snap("viewer", frozenset({Permission.MARKETDATA_READ})), 1)
    assert frames[0]["t"] == "permission_change"
    assert frames[0]["p"]["roles"] == ["viewer"]
    assert [(f["t"], f["ch"]) for f in frames[1:]] == [("revoked", "orders")]
    assert frames[1]["p"]["reason"] == "permission_revoked"
    assert not conn.may_submit_order()
    assert conn.topics == {"book.BTCUSDT"}


OTHER = uuid.uuid4()


def _mgr(grants: tuple[AccountGrant, ...]) -> PrincipalSnapshot:
    return PrincipalSnapshot(uuid.UUID(int=2), frozenset({"manager"}), MGR, grants)


def test_manager_account_less_sub_on_account_scoped_topic_is_rejected() -> None:
    m = _mgr((AccountGrant(ACC, True, True, False),))
    for fam in ("orders", "positions", "executions", "wallet", "rules"):
        d = check_subscribe(
            m.__class__(m.user_id, m.roles, frozenset(Permission), m.account_grants), fam
        )
        assert isinstance(d, Deny) and d.reason is DenyReason.OBJECT_REQUIRED
    assert isinstance(check_subscribe(m, "orders", exchange_account_id=OTHER), Deny)
    assert isinstance(check_subscribe(m, "orders", exchange_account_id=ACC), Allow)


def test_owner_needs_an_account_id_but_any_account_is_allowed() -> None:
    o = PrincipalSnapshot(uuid.UUID(int=3), frozenset({"owner"}), ALL)
    assert isinstance(check_subscribe(o, "orders", exchange_account_id=OTHER), Allow)


def test_lost_account_grant_revokes_subscription_with_scope_reason() -> None:
    conn = ConnectionAuthz(_mgr((AccountGrant(ACC, True, True, False),)))
    assert isinstance(conn.subscribe("orders", exchange_account_id=ACC), Allow)
    frames = conn.apply_snapshot(_mgr(()), 5)
    assert [(f["t"], f.get("ch")) for f in frames] == [
        ("permission_change", None),
        ("revoked", "orders"),
    ]
    assert frames[1]["p"]["reason"] == "account_scope_changed"
    assert conn.subs == set()


def test_owner_unaffected_by_grant_snapshot_refresh() -> None:
    o = PrincipalSnapshot(uuid.UUID(int=3), frozenset({"owner"}), ALL)
    conn = ConnectionAuthz(o)
    conn.subscribe("orders", exchange_account_id=OTHER)
    assert conn.apply_snapshot(o, 1)[1:] == []
    assert conn.topics == {"orders"}


def _run_sub(conn: ConnectionAuthz, entry: Any) -> dict[str, Any]:
    sent: list[dict[str, Any]] = []

    async def send(f: dict[str, Any]) -> None:
        sent.append(f)

    asyncio.run(handle_sub(conn, {"id": "x", "p": {"topics": [entry, 7]}}, send))
    result: dict[str, Any] = sent[0]["p"]["results"][0]
    return result


def test_handle_sub_rejects_malformed_and_partial_account_lists() -> None:
    conn = ConnectionAuthz(_mgr((AccountGrant(ACC, True, True, False),)))
    bad = {"ch": "orders", "opts": {"exchange_account_ids": ["not-a-uuid"]}}
    assert _run_sub(conn, bad)["error"]["code"] == "bad_request"
    assert _run_sub(conn, {"ch": "orders", "opts": {"exchange_account_ids": []}})["ok"] is False
    mixed = {"ch": "orders", "opts": {"exchange_account_ids": [str(ACC), str(OTHER)]}}
    assert _run_sub(conn, mixed)["error"]["code"] == "account_scope_denied"
    assert conn.subs == set()


def test_registry_without_connections_is_noop() -> None:
    async def resolve(uid: uuid.UUID) -> PrincipalSnapshot:
        raise AssertionError("must not resolve")

    asyncio.run(ConnectionRegistry(resolve, lambda: 0).roles_changed(uuid.uuid4()))
