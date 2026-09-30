"""WS auth_ok permissions, per-subscribe check, mid-connection downgrade (QA #1648 d1)."""

from __future__ import annotations

import uuid

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, Allow, Deny, PrincipalSnapshot
from candleviewer.ws.permissions import ConnectionAuthz, auth_ok_payload, check_subscribe

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
    conn.subscribe("orders")
    assert conn.may_submit_order()
    frames = conn.apply_snapshot(_snap("viewer", frozenset({Permission.MARKETDATA_READ})), 1)
    assert frames[0]["t"] == "permission_change"
    assert frames[0]["p"]["roles"] == ["viewer"]
    assert [(f["t"], f["ch"]) for f in frames[1:]] == [("revoked", "orders")]
    assert frames[1]["p"]["reason"] == "permission_revoked"
    assert not conn.may_submit_order()
    assert conn.topics == {"book.BTCUSDT"}
