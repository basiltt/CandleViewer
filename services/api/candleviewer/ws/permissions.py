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

import asyncio
import contextlib
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.scopes import Allow, Deny, DenyReason, PrincipalSnapshot, decide
from candleviewer.ws.limits import (
    FANOUT_SEND_TIMEOUT_S,
    MAX_SUBSCRIPTIONS,
    MAX_TOPICS_PER_SUB,
)

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
    # Account-scoped families REQUIRE an account id: `decide()` denies a
    # GRANTED_ACCOUNTS check without one (OBJECT_REQUIRED), so an
    # account-less `orders`/`positions`/... sub fails closed (#1654 IDOR).
    return decide(principal, permission, scope=scope, exchange_account_id=exchange_account_id)


@dataclass
class ConnectionAuthz:
    """Authorisation state of one authenticated WS connection."""

    principal: PrincipalSnapshot
    #: Live subscriptions as (topic, account id or None for unscoped topics).
    subs: set[tuple[str, uuid.UUID | None]] = field(default_factory=set)

    @property
    def topics(self) -> set[str]:
        return {topic for topic, _ in self.subs}

    def at_capacity(self, needed: int = 1) -> bool:
        """True when adding `needed` new subscriptions would exceed the
        per-connection cap (C-2.18, `limits.MAX_SUBSCRIPTIONS`)."""
        return len(self.subs) + needed > MAX_SUBSCRIPTIONS

    def subscribe(
        self, topic: str, *, exchange_account_id: uuid.UUID | None = None
    ) -> Allow | Deny | None:
        if (topic, exchange_account_id) not in self.subs and self.at_capacity():
            return Deny(DenyReason.MISSING_PERMISSION, Permission.MARKETDATA_READ, Scope.NONE)
        decision = check_subscribe(self.principal, topic, exchange_account_id=exchange_account_id)
        if decision is None or isinstance(decision, Allow):
            self.subs.add((topic, exchange_account_id))
        return decision

    def unsubscribe(self, topic: str) -> None:
        self.subs = {s for s in self.subs if s[0] != topic}

    def may_submit_order(self) -> bool:
        return isinstance(decide(self.principal, Permission.ORDERS_WRITE), Allow)

    def apply_snapshot(self, new: PrincipalSnapshot, now_ms: int) -> list[dict[str, Any]]:
        """Swap in `new`; return frames to send: one `permission_change`
        then a `revoked` per subscription the new snapshot forbids."""
        self.principal = new
        frames: list[dict[str, Any]] = [
            {"t": "permission_change", "ts": now_ms, "p": auth_ok_payload(new)}
        ]
        revoked: dict[str, Deny] = {}
        for topic, account in sorted(self.subs, key=lambda s: (s[0], str(s[1]))):
            # Re-validate WITH the account id so a lost grant revokes too.
            decision = check_subscribe(new, topic, exchange_account_id=account)
            if isinstance(decision, Deny):
                revoked.setdefault(topic, decision)
        for topic, deny in revoked.items():
            self.unsubscribe(topic)
            missing_perm = deny.reason is DenyReason.MISSING_PERMISSION
            frames.append(
                {
                    "t": "revoked",
                    "ch": topic,
                    "ts": now_ms,
                    "p": {
                        "reason": "permission_revoked" if missing_perm else "account_scope_changed",
                        "message": f"Access to {topic} was withdrawn.",
                    },
                }
            )
        return frames


class ConnectionRegistry:
    """Live authenticated sockets; implements `PermissionChangeNotifier`.

    The WS handler registers a `ConnectionAuthz` plus a `send` coroutine at
    `auth_ok` (payload from `auth_ok_payload`), routes `sub` through
    `ConnectionAuthz.subscribe` and unregisters on close.
    """

    def __init__(
        self,
        resolve: Callable[[uuid.UUID], Awaitable[PrincipalSnapshot]],
        clock_ms: Callable[[], int],
    ) -> None:
        self._resolve = resolve
        self._clock_ms = clock_ms
        self._conns: dict[uuid.UUID, list[tuple[ConnectionAuthz, Any, Any]]] = {}
        self.send_timeout_s = FANOUT_SEND_TIMEOUT_S

    def register(self, authz: ConnectionAuthz, send: Any, close: Any = None) -> None:
        """`close` (async, no args) is called to evict a stalled socket."""
        self._conns.setdefault(authz.principal.user_id, []).append((authz, send, close))

    def unregister(self, authz: ConnectionAuthz) -> None:
        entries = self._conns.get(authz.principal.user_id, [])
        self._conns[authz.principal.user_id] = [e for e in entries if e[0] is not authz]

    async def resolve(self, user_id: uuid.UUID) -> PrincipalSnapshot:
        return await self._resolve(user_id)

    async def roles_changed(self, user_id: uuid.UUID) -> None:
        """Role/grant change: push `permission_change` and drop now-forbidden
        subscriptions on every live socket of `user_id`."""
        entries = list(self._conns.get(user_id, ()))
        if not entries:
            return
        snap = await self._resolve(user_id)
        for authz, send, close in entries:
            # Subscriptions are dropped synchronously here, before any I/O.
            frames = authz.apply_snapshot(snap, self._clock_ms())
            try:
                async with asyncio.timeout(self.send_timeout_s):
                    for frame in frames:
                        await send(frame)
            except (TimeoutError, OSError, RuntimeError):
                # C-2.18: a stalled/broken client must not block the role
                # change or the other sockets -> evict it.
                self.unregister(authz)
                if close is not None:
                    with contextlib.suppress(Exception):
                        async with asyncio.timeout(self.send_timeout_s):
                            await close()


Send = Any  # async (frame: dict) -> None


async def open_connection(
    registry: ConnectionRegistry,
    principal: PrincipalSnapshot,
    send: Send,
    *,
    close: Any = None,
    **extra: Any,
) -> ConnectionAuthz:
    """Gateway hook for a verified `auth`: registers the socket for
    `permission_change` pushes and sends `auth_ok` with permissions/scope."""
    authz = ConnectionAuthz(principal)
    registry.register(authz, send, close)
    await send({"t": "auth_ok", "p": auth_ok_payload(principal, **extra)})
    return authz


def _account_ids(entry: Any) -> list[uuid.UUID | None] | None:
    """`opts.exchange_account_ids` of a topic entry (§5.1); `[None]` when
    absent, `None` when malformed (rejected, fail closed)."""
    opts = entry.get("opts") if isinstance(entry, dict) else None
    raw = (opts or {}).get("exchange_account_ids") if isinstance(opts, dict) else None
    if raw is None:
        return [None]
    if not isinstance(raw, list) or not raw:
        return None
    try:
        return [uuid.UUID(str(a)) for a in raw]
    except ValueError:
        return None


def _sub_result(ch: str, decisions: list[Allow | Deny | None]) -> dict[str, Any]:
    deny = next((d for d in decisions if isinstance(d, Deny)), None)
    if deny is None:
        return {"ch": ch, "ok": True}
    code = "forbidden" if deny.reason is DenyReason.MISSING_PERMISSION else "account_scope_denied"
    return {"ch": ch, "ok": False, "error": {"code": code, "message": f"Not permitted: {ch}."}}


def _limit_result(ch: str, code: str) -> dict[str, Any]:
    return {"ch": ch, "ok": False, "error": {"code": code, "message": f"Limit reached: {ch}."}}


async def handle_sub(authz: ConnectionAuthz, frame: dict[str, Any], send: Send) -> None:
    """Gateway hook for a `sub` frame: every topic (and every account id in
    `opts.exchange_account_ids`) is checked against permission AND account
    scope (§6.3); one `sub_ok` with a per-topic result (§5.2). A topic is
    only subscribed when every requested account is allowed."""
    topics = (frame.get("p") or {}).get("topics") or []
    results: list[dict[str, Any]] = []
    if not isinstance(topics, list):
        topics = []
    for index, entry in enumerate(topics):
        ch = entry.get("ch") if isinstance(entry, dict) else entry
        if not isinstance(ch, str):
            continue
        if index >= MAX_TOPICS_PER_SUB:
            results.append(_limit_result(ch, "too_many_topics"))
            continue
        accounts = _account_ids(entry)
        if accounts is None:
            results.append(
                {"ch": ch, "ok": False, "error": {"code": "bad_request", "message": "bad opts"}}
            )
            continue
        new = sum((ch, a) not in authz.subs for a in accounts)
        if authz.at_capacity(new):
            results.append(_limit_result(ch, "subscription_limit"))
            continue
        decisions = [check_subscribe(authz.principal, ch, exchange_account_id=a) for a in accounts]
        result = _sub_result(ch, decisions)
        if result["ok"]:
            for a in accounts:
                authz.subscribe(ch, exchange_account_id=a)
        results.append(result)
    await send({"t": "sub_ok", "id": frame.get("id"), "p": {"results": results}})


def close_connection(registry: ConnectionRegistry, authz: ConnectionAuthz) -> None:
    registry.unregister(authz)
