"""Runtime enforcement tests for `candleviewer.auth.scopes.enforce`
(PR #1629 review finding 1: no route returned a runtime 403 and
`rbac.denied` was not audited).

These tests wire `enforce()` as a real FastAPI dependency on a route and
assert the actual HTTP response is 403, and that a denial calls the audit
emitter with `rbac.denied` naming the permission and scope.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.scopes import (
    AccountGrant,
    ForbiddenError,
    PrincipalSnapshot,
    enforce,
)

ACCOUNT_A = uuid.UUID("a1000000-0000-4000-8000-000000000001")
ACCOUNT_B = uuid.UUID("a1000000-0000-4000-8000-000000000002")


class _FakeEmitter:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def emit(self, action: str, **kwargs: Any) -> None:
        self.calls.append({"action": action, **kwargs})


def _viewer_principal() -> PrincipalSnapshot:
    return PrincipalSnapshot(
        user_id=uuid.uuid4(),
        roles=frozenset({"viewer"}),
        permissions=frozenset({Permission.ORDERS_READ}),
    )


def _manager_principal(*, grants: tuple[AccountGrant, ...] = ()) -> PrincipalSnapshot:
    return PrincipalSnapshot(
        user_id=uuid.uuid4(),
        roles=frozenset({"manager"}),
        permissions=frozenset({Permission.ORDERS_WRITE}),
        account_grants=grants,
    )


def _build_app(principal: PrincipalSnapshot, emitter: _FakeEmitter) -> FastAPI:
    app = FastAPI()

    async def _require_orders_write(
        exchange_account_id: uuid.UUID | None = None,
    ) -> None:
        try:
            await enforce(
                principal,
                Permission.ORDERS_WRITE,
                scope=Scope.GRANTED_ACCOUNTS,
                exchange_account_id=exchange_account_id,
                requires_trade=True,
                emitter=emitter,
            )
        except ForbiddenError as exc:
            raise HTTPException(status_code=403, detail=exc.deny.reason.value) from exc

    @app.post("/orders/{exchange_account_id}")
    async def submit_order(
        exchange_account_id: uuid.UUID,
        _: None = Depends(_require_orders_write),
    ) -> dict[str, str]:
        return {"status": "accepted"}

    return app


def test_route_returns_runtime_403_on_deny() -> None:
    """PR #1629 review finding 1: a route wired to `enforce()` must return
    an actual HTTP 403 at runtime, not just a pure `Deny` value nobody
    consumes."""
    principal = _manager_principal(
        grants=(AccountGrant(ACCOUNT_A, can_view=True, can_trade=True, frozen=False),)
    )
    emitter = _FakeEmitter()
    client = TestClient(_build_app(principal, emitter))

    response = client.post(f"/orders/{ACCOUNT_B}")

    assert response.status_code == 403
    assert response.json()["detail"] == "account_not_granted"


def test_route_allows_when_decide_allows() -> None:
    principal = _manager_principal(
        grants=(AccountGrant(ACCOUNT_A, can_view=True, can_trade=True, frozen=False),)
    )
    emitter = _FakeEmitter()
    client = TestClient(_build_app(principal, emitter))

    response = client.post(f"/orders/{ACCOUNT_A}")

    assert response.status_code == 200
    assert emitter.calls == []


def test_deny_is_audited_as_rbac_denied_naming_permission_and_scope() -> None:
    """PR #1629 review finding 1 + finding 2: every denial audits
    `rbac.denied` and the reason string names both the permission and the
    scope, not just a bare reason code."""
    principal = _viewer_principal()
    emitter = _FakeEmitter()
    client = TestClient(_build_app(principal, emitter))

    response = client.post(f"/orders/{ACCOUNT_A}")

    assert response.status_code == 403
    assert len(emitter.calls) == 1
    call = emitter.calls[0]
    assert call["action"] == "rbac.denied"
    assert call["severity"] == "warning"
    assert "orders:write" in call["reason"]
    assert "granted_accounts" in call["reason"]


@pytest.mark.asyncio
async def test_enforce_raises_forbidden_without_emitter() -> None:
    """`emitter` is optional (bare unit tests, pre-audit-wiring call sites)
    but a denial always raises `ForbiddenError` regardless."""
    principal = _viewer_principal()
    with pytest.raises(ForbiddenError) as exc_info:
        await enforce(principal, Permission.ORDERS_WRITE)
    assert exc_info.value.deny.permission == Permission.ORDERS_WRITE
