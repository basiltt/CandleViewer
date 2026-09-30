"""RBAC policy decision point (M18, E09-T03).

`decide()` answers "may this principal do this thing to this object?",
pure and synchronous over a per-request `PrincipalSnapshot` (roles,
permissions, account scope, loaded once — `docs/plan/20-architecture.md`
P8, §3.10). No ambient context: object-scoped decisions (account id) take
the object as an explicit argument, so the function is trivially testable
and the OMS validator's later use (E39+) stays honest.

Deny-by-default: `decide()` never raises `AllowUnknownPermission` — an
unresolvable principal, an unknown permission code, or a missing account
grant all yield `Deny`. Denials never leak whether the object exists (a
manager asking about another manager's account gets the same `Deny` as for
a non-existent one) — callers must render every `Deny` as a uniform 403,
never branching on `reason` for user-facing text beyond the fixed
`forbidden` body (ticket "403 semantics").
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum

from candleviewer.auth.generated_permissions import Permission, Scope


class DenyReason(StrEnum):
    """Machine-readable reason code for the uniform `forbidden` body
    (ticket "403 semantics" / SCR-154)."""

    MISSING_PERMISSION = "missing_permission"
    ACCOUNT_NOT_GRANTED = "account_not_granted"
    ACCOUNT_FROZEN = "account_frozen"
    TRADING_NOT_GRANTED = "trading_not_granted"
    OBJECT_REQUIRED = "object_required"


@dataclass(frozen=True)
class AccountGrant:
    """One row of `user_account_access` (`21-database-schema.md` §3.1.3):
    `can_view`/`can_trade`/`frozen` for one `exchange_account_id`."""

    exchange_account_id: uuid.UUID
    can_view: bool
    can_trade: bool
    frozen: bool


@dataclass(frozen=True)
class PrincipalSnapshot:
    """A principal's roles, resolved permissions and account grants, loaded
    once per request (or once per WS connection, refreshed on a role/access
    change bus event) — never re-queried per decision.

    `account_grants` is empty for `owner`: per the ticket's own text ("empty
    `allowed_account_ids` means all, owner only"), an owner's absence of any
    row in `user_account_access` means "every account", not "no account" —
    `decide()` special-cases `is_owner` for exactly this reason rather than
    trying to represent "all accounts" as a sentinel grant row.
    """

    user_id: uuid.UUID
    roles: frozenset[str]
    permissions: frozenset[Permission]
    account_grants: tuple[AccountGrant, ...] = field(default_factory=tuple)

    @property
    def is_owner(self) -> bool:
        return "owner" in self.roles

    def grant_for(self, exchange_account_id: uuid.UUID) -> AccountGrant | None:
        for grant in self.account_grants:
            if grant.exchange_account_id == exchange_account_id:
                return grant
        return None


@dataclass(frozen=True)
class Allow:
    """The decision was permitted."""


@dataclass(frozen=True)
class Deny:
    """The decision was refused; `reason` is machine-readable only — never
    used to distinguish "object doesn't exist" from "object not yours" in
    the HTTP response (ticket "Security notes")."""

    reason: DenyReason


Decision = Allow | Deny


def decide(
    principal: PrincipalSnapshot,
    permission: Permission,
    *,
    scope: Scope = Scope.NONE,
    exchange_account_id: uuid.UUID | None = None,
    requires_trade: bool = False,
) -> Decision:
    """Deny-by-default policy decision.

    `scope` mirrors the operation's `x-rbac.scope`:
    - `Scope.NONE`: the permission alone decides (no object).
    - `Scope.SELF`: caller-scoped; the router resolves "self" before
      calling `decide()` — this function only ever checks the permission
      (there is no cross-user "self" check to make here).
    - `Scope.GRANTED_ACCOUNTS`: `exchange_account_id` must be supplied and
      the principal must hold a live, unfrozen grant for it; `owner` is
      implicitly granted every account (empty `user_account_access` rows
      for owner means "all", per the ticket's own text).
    """
    if permission not in principal.permissions:
        return Deny(DenyReason.MISSING_PERMISSION)

    if scope is not Scope.GRANTED_ACCOUNTS:
        return Allow()

    if exchange_account_id is None:
        return Deny(DenyReason.OBJECT_REQUIRED)

    if principal.is_owner:
        return Allow()

    grant = principal.grant_for(exchange_account_id)
    if grant is None or not grant.can_view:
        return Deny(DenyReason.ACCOUNT_NOT_GRANTED)
    if grant.frozen:
        return Deny(DenyReason.ACCOUNT_FROZEN)
    if requires_trade and not grant.can_trade:
        return Deny(DenyReason.TRADING_NOT_GRANTED)

    return Allow()
