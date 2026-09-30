"""Decision-matrix tests for `candleviewer.auth.scopes.decide` (E09-T03).

Covers the ticket's Gherkin scenarios that are pure decision-point logic
(deny-by-default, manager cross-account isolation, frozen/trade-scope
checks); the WS-propagation and owner-floor scenarios are integration-level
and out of this module's unit-test scope (see ticket "Test plan").
"""

from __future__ import annotations

import uuid

import pytest

from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.scopes import (
    AccountGrant,
    Allow,
    Deny,
    DenyReason,
    PrincipalSnapshot,
    decide,
)

ACCOUNT_A = uuid.UUID("a1000000-0000-4000-8000-000000000001")
ACCOUNT_B = uuid.UUID("a1000000-0000-4000-8000-000000000002")


def _manager(*, grants: tuple[AccountGrant, ...] = ()) -> PrincipalSnapshot:
    return PrincipalSnapshot(
        user_id=uuid.uuid4(),
        roles=frozenset({"manager"}),
        permissions=frozenset({Permission.ORDERS_READ, Permission.ORDERS_WRITE}),
        account_grants=grants,
    )


def _owner() -> PrincipalSnapshot:
    return PrincipalSnapshot(
        user_id=uuid.uuid4(),
        roles=frozenset({"owner"}),
        permissions=frozenset(Permission),
    )


def _viewer() -> PrincipalSnapshot:
    return PrincipalSnapshot(
        user_id=uuid.uuid4(),
        roles=frozenset({"viewer"}),
        permissions=frozenset({Permission.ORDERS_READ}),
    )


def test_missing_permission_denies_by_default() -> None:
    principal = _viewer()
    result = decide(principal, Permission.ORDERS_WRITE)
    assert isinstance(result, Deny)
    assert result.reason == DenyReason.MISSING_PERMISSION
    # PR #1629 review finding 2: the denial must name the permission and
    # scope so the audited `rbac.denied` record can be built from it alone.
    assert result.permission == Permission.ORDERS_WRITE
    assert result.scope == Scope.NONE


def test_scope_none_allows_on_permission_alone() -> None:
    principal = _manager()
    result = decide(principal, Permission.ORDERS_READ, scope=Scope.NONE)
    assert isinstance(result, Allow)


def test_granted_accounts_requires_object() -> None:
    principal = _manager(
        grants=(AccountGrant(ACCOUNT_A, can_view=True, can_trade=True, frozen=False),)
    )
    result = decide(principal, Permission.ORDERS_READ, scope=Scope.GRANTED_ACCOUNTS)
    assert isinstance(result, Deny)
    assert result.reason == DenyReason.OBJECT_REQUIRED


def test_manager_cannot_reach_another_managers_account() -> None:
    """Ticket scenario: "A manager cannot reach another manager's account"."""
    principal = _manager(
        grants=(AccountGrant(ACCOUNT_A, can_view=True, can_trade=True, frozen=False),)
    )
    result = decide(
        principal,
        Permission.ORDERS_READ,
        scope=Scope.GRANTED_ACCOUNTS,
        exchange_account_id=ACCOUNT_B,
    )
    assert isinstance(result, Deny)
    assert result.reason == DenyReason.ACCOUNT_NOT_GRANTED


def test_manager_can_reach_own_granted_account() -> None:
    principal = _manager(
        grants=(AccountGrant(ACCOUNT_A, can_view=True, can_trade=True, frozen=False),)
    )
    result = decide(
        principal,
        Permission.ORDERS_READ,
        scope=Scope.GRANTED_ACCOUNTS,
        exchange_account_id=ACCOUNT_A,
    )
    assert isinstance(result, Allow)


def test_frozen_account_denies_even_with_grant() -> None:
    principal = _manager(
        grants=(AccountGrant(ACCOUNT_A, can_view=True, can_trade=True, frozen=True),)
    )
    result = decide(
        principal,
        Permission.ORDERS_READ,
        scope=Scope.GRANTED_ACCOUNTS,
        exchange_account_id=ACCOUNT_A,
    )
    assert isinstance(result, Deny)
    assert result.reason == DenyReason.ACCOUNT_FROZEN


def test_view_only_grant_denies_trade_when_requires_trade() -> None:
    principal = _manager(
        grants=(AccountGrant(ACCOUNT_A, can_view=True, can_trade=False, frozen=False),)
    )
    result = decide(
        principal,
        Permission.ORDERS_WRITE,
        scope=Scope.GRANTED_ACCOUNTS,
        exchange_account_id=ACCOUNT_A,
        requires_trade=True,
    )
    assert isinstance(result, Deny)
    assert result.reason == DenyReason.TRADING_NOT_GRANTED


def test_owner_reaches_any_account_with_no_grant_rows() -> None:
    """Ticket text: "empty allowed_account_ids means all, owner only"."""
    principal = _owner()
    result = decide(
        principal,
        Permission.ORDERS_WRITE,
        scope=Scope.GRANTED_ACCOUNTS,
        exchange_account_id=ACCOUNT_B,
        requires_trade=True,
    )
    assert isinstance(result, Allow)


def test_missing_permission_short_circuits_before_scope_check() -> None:
    """A principal without the base permission is denied even for an
    account they are granted — permission is checked first."""
    principal = _manager(
        grants=(AccountGrant(ACCOUNT_A, can_view=True, can_trade=True, frozen=False),)
    )
    result = decide(
        principal,
        Permission.KEYS_MANAGE,
        scope=Scope.GRANTED_ACCOUNTS,
        exchange_account_id=ACCOUNT_A,
    )
    assert isinstance(result, Deny)
    assert result.reason == DenyReason.MISSING_PERMISSION


@pytest.mark.parametrize(
    "role,permission,expected",
    [
        ("owner", Permission.KEYS_MANAGE, Allow),
        ("owner", Permission.USERS_WRITE, Allow),
        ("manager", Permission.USERS_WRITE, Deny),
        ("manager", Permission.KEYS_MANAGE, Deny),
        # manager holds killswitch:write scoped to their own granted
        # accounts (ticket "Role seeds": "no killswitch:write beyond own
        # scope" — the seed grants the base permission; GRANTED_ACCOUNTS
        # scope is what narrows it, covered by the account-scope tests
        # above, not this permission-only matrix).
        ("manager", Permission.KILLSWITCH_WRITE, Allow),
        ("viewer", Permission.ORDERS_WRITE, Deny),
        ("viewer", Permission.AUDIT_READ, Allow),
    ],
)
def test_role_permission_matrix(
    role: str, permission: Permission, expected: type[Allow] | type[Deny]
) -> None:
    """Exhaustive-flavoured matrix over the seed's role_permissions grants
    (ticket "Role seeds": manager has no `users:write`/`keys:manage`/
    `killswitch:write` beyond own scope; viewer includes audit read)."""
    import json
    from pathlib import Path

    seed_path = Path(__file__).resolve().parents[3] / "candleviewer" / "auth" / "rbac_seed.json"
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    granted_codes = seed["role_permissions"][role]
    has_permission = granted_codes == ["*"] or permission.value in granted_codes

    principal = PrincipalSnapshot(
        user_id=uuid.uuid4(),
        roles=frozenset({role}),
        permissions=frozenset(Permission) if has_permission else frozenset(),
    )
    result = decide(principal, permission)
    assert isinstance(result, expected)


def test_custom_role_named_owner_is_rejected() -> None:
    """PR #1629 review finding 3: `is_owner` matches the role name alone,
    so a `PrincipalSnapshot` must never be constructible with a role
    outside the DB's fixed `role_name` ENUM (`owner`/`manager`/`viewer`) —
    a hypothetical custom role called "owner" cannot silently inherit the
    owner floor's account-grant bypass."""
    with pytest.raises(ValueError, match="unknown role"):
        PrincipalSnapshot(
            user_id=uuid.uuid4(),
            roles=frozenset({"owner_impersonator"}),
            permissions=frozenset({Permission.ORDERS_WRITE}),
        )
