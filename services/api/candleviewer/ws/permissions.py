"""WS authorisation (E09-T03, QA #1648 defect 1; `23-ws-protocol.md` §4.3, §6.3, §9.5).

- `auth_ok_payload`: identity, roles, resolved permissions, account scope.
- `check_subscribe`: per-topic permission check against the §6.3 matrix
  (unknown topic family or missing permission -> deny; fail-closed).
- `ConnectionAuthz`: per-connection state. `apply_snapshot` swaps in a new
  principal snapshot after a role/grant change and returns the
  `permission_change` frame plus the `revoked` frames for subscriptions the
  new snapshot no longer permits, so a downgrade takes effect mid-connection.
  `may_submit_order` refuses orders once `orders:write` is gone.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.scopes import Allow, Deny, DenyReason, PrincipalSnapshot, decide

#: §6.3 topic family -> (permission, scope). `system` is implicit (no check).
TOPIC_PERMISSIONS: dict[str, tuple[Permission, Scope]] = {
    **{
        fam: (Permission.MARKETDATA_READ, Scope.NONE)
        for fam in (
            "book",
            "trades",
            "bars",
            "footprint",
            "heatmap",
            "profile",
            "metrics",
            "ticker",
            "liquidations",
        )
    },
    "orders": (Permission.ORDERS_READ, Scope.GRANTED_ACCOUNTS),
    "trade_groups": (Permission.ORDERS_READ, Scope.GRANTED_ACCOUNTS),
    "positions": (Permission.POSITIONS_READ, Scope.GRANTED_ACCOUNTS),
    "executions": (Permission.EXECUTIONS_READ, Scope.GRANTED_ACCOUNTS),
    "wallet": (Permission.ACCOUNTS_READ, Scope.GRANTED_ACCOUNTS),
    "rules": (Permission.RULES_READ, Scope.GRANTED_ACCOUNTS),
    "alerts": (Permission.ALERTS_READ, Scope.SELF),
    "recorder": (Permission.RECORDING_READ, Scope.NONE),
}


def topic_family(topic: str) -> str:
    return topic.split(".", 1)[0]


def auth_ok_payload(principal: PrincipalSnapshot, **extra: Any) -> dict[str, Any]:
    """`auth_ok` `p` body: roles, resolved permissions and account scope."""
    return {
        "user_id": str(principal.user_id),
        "roles": sorted(principal.roles),
        "permissions": sorted(p.value for p in principal.permissions),
        # Empty for owner = all accounts (ticket); viewable grants otherwise.
        "account_scope": sorted(
            str(g.exchange_account_id) for g in principal.account_grants if g.can_view
        ),
        **extra,
    }


def check_subscribe(
    principal: PrincipalSnapshot,
    topic: str,
    *,
    exchange_account_id: uuid.UUID | None = None,
) -> Allow | Deny | None:
    """Decision for a `sub` of `topic`. Returns `None` for the implicit
    `system` topic (always allowed) and `Deny` for unknown families."""
    family = topic_family(topic)
    if family == "system":
        return None
    entry = TOPIC_PERMISSIONS.get(family)
    if entry is None:
        return Deny(DenyReason.MISSING_PERMISSION, Permission.MARKETDATA_READ, Scope.NONE)
    permission, scope = entry
    if scope is Scope.GRANTED_ACCOUNTS and exchange_account_id is None:
        # Account-less subscribe: permission alone decides; the gateway
        # narrows the stream to granted accounts (§6.3 "scope narrowing").
        scope = Scope.NONE
    return decide(principal, permission, scope=scope, exchange_account_id=exchange_account_id)


@dataclass
class ConnectionAuthz:
    """Authorisation state of one authenticated WS connection."""

    principal: PrincipalSnapshot
    topics: set[str] = field(default_factory=set)

    def subscribe(self, topic: str, **kw: Any) -> Allow | Deny | None:
        decision = check_subscribe(self.principal, topic, **kw)
        if decision is None or isinstance(decision, Allow):
            self.topics.add(topic)
        return decision

    def may_submit_order(self) -> bool:
        return isinstance(decide(self.principal, Permission.ORDERS_WRITE), Allow)

    def apply_snapshot(self, new: PrincipalSnapshot, now_ms: int) -> list[dict[str, Any]]:
        """Swap in `new`; return frames to send: one `permission_change`
        then a `revoked` per subscription the new snapshot forbids."""
        self.principal = new
        frames: list[dict[str, Any]] = [
            {"t": "permission_change", "ts": now_ms, "p": auth_ok_payload(new)}
        ]
        for topic in sorted(self.topics):
            decision = check_subscribe(new, topic)
            if isinstance(decision, Deny):
                self.topics.discard(topic)
                frames.append(
                    {
                        "t": "revoked",
                        "ch": topic,
                        "ts": now_ms,
                        "p": {
                            "reason": "permission_revoked",
                            "message": f"Permission {decision.permission.value} was withdrawn.",
                        },
                    }
                )
        return frames
