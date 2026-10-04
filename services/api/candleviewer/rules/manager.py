"""Rule store, versioning and mode switching (E35-S01).

Storage is behind `RuleStore` (the Postgres adapter lives in M10 and lands with the
integration PR); `InMemoryRuleStore` backs unit/contract tests. Versions are immutable;
the optimistic-concurrency token is the version number, never a timestamp.
"""

from __future__ import annotations

import copy
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import ValidationError

from candleviewer.rules.arming import ArmingFacts, check_arming
from candleviewer.rules.ir import Rule, ir_hash
from candleviewer.rules.lifecycle import MODES, LifecycleError, RuleLifecycle, mode_of
from candleviewer.rules.validator import validate_rule
from candleviewer.rules.vocabulary import MetricRegistry

COMPILER_VERSION = "1.0.0"
#: Bounded replay cache for `Idempotency-Key` (C-2.18); see `set_mode`.
IDEM_CACHE_MAX = 4096
_ORDER_ACTIONS = frozenset(
    {
        "place_order",
        "scale_in",
        "scale_out",
        "reverse_position",
        "flatten_position",
        "flatten_all_positions",
        "modify_stop_loss",
        "modify_take_profit",
        "move_to_breakeven",
        "cancel_order",
        "cancel_all_orders",
    }
)


class RuleError(Exception):
    def __init__(self, status: int, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra


@dataclass
class VersionRow:
    id: str
    rule_id: str
    version: int
    ir: dict[str, Any]
    ir_hash: str
    compiler_version: str
    notes: str
    author: str
    session: str


@dataclass
class RuleRow:
    id: str
    name: str
    owner: str
    mode: str = "disabled"
    scope: str = "global"
    active_version_id: str | None = None
    latest_version: int = 0
    last_editor: str = ""
    last_session: str = ""
    deleted: bool = False
    simulated_hashes: set[str] = field(default_factory=set)
    simulation_fires: int = 0
    simulation_hours: float = 0.0
    versions: list[VersionRow] = field(default_factory=list)
    armed_by: str | None = None
    #: `rules.disabled_reason`: which B9 state a `disabled` row projects (draft / disarmed /
    #: kill_switched); `rules.lifecycle` hydrates the chart from it.
    disabled_reason: str | None = None


class RuleStore(Protocol):
    async def get(self, rule_id: str) -> RuleRow | None: ...
    async def put(self, row: RuleRow) -> None: ...
    async def all(self) -> list[RuleRow]: ...


class InMemoryRuleStore:
    def __init__(self) -> None:
        self._rows: dict[str, RuleRow] = {}

    async def get(self, rule_id: str) -> RuleRow | None:
        return self._rows.get(rule_id)

    async def put(self, row: RuleRow) -> None:
        self._rows[row.id] = row

    async def all(self) -> list[RuleRow]:
        return list(self._rows.values())


@dataclass(frozen=True, slots=True)
class Actor:
    user_id: str
    session_id: str
    perms: frozenset[str] = frozenset()
    granted_accounts: frozenset[str] = frozenset()
    is_owner: bool = False
    step_up_fresh: bool = False
    #: Consumes a fresh one-shot step-up grant; True on success (live arming only).
    consume_step_up: Callable[[], Awaitable[bool]] | None = None


Audit = Callable[[str, dict[str, Any]], Awaitable[None]]
Broadcast = Callable[[dict[str, Any]], Awaitable[None]]
Metric = Callable[[str, dict[str, str]], None]


async def _noop_audit(_action: str, _payload: dict[str, Any]) -> None:
    return None


async def _noop_bc(_payload: dict[str, Any]) -> None:
    return None


def _noop_metric(_name: str, _labels: dict[str, str]) -> None:
    return None


_DRAFT_TO_ARMED = (
    "A rule cannot be armed straight from disabled. Move it to simulate first, then arm it."
)


def _illegal(leaf: str, target: str) -> str:
    """User-facing refusal for a change the B9 chart does not accept from *leaf*."""
    if target == "armed" and leaf == "draft":
        return _DRAFT_TO_ARMED
    if target == "armed" and leaf == "kill_switched":
        return "This rule was stopped by the kill switch. Re-arming needs a fresh step-up code."
    if target == "armed":
        return "This rule has not met its simulation requirement, so it cannot be armed yet."
    return f"A rule cannot change from {mode_of(leaf)} to {target} right now."


def quarantine_path(ir: dict[str, Any]) -> str | None:
    """JSON path of the first schema violation, or None when the stored IR is sound."""
    try:
        Rule.model_validate(ir)
    except ValidationError as exc:
        return "/" + "/".join(str(p) for p in exc.errors()[0]["loc"])
    return None


class RulesManager:
    def __init__(
        self,
        store: RuleStore,
        registry: MetricRegistry,
        *,
        audit: Audit = _noop_audit,
        broadcast: Broadcast = _noop_bc,
        on_metric: Metric = _noop_metric,
        lifecycle: RuleLifecycle | None = None,
    ) -> None:
        self._s = store
        self._reg = registry
        self._audit = audit
        self._bc = broadcast
        self._metric = on_metric
        self._idem: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self.lifecycle = lifecycle or RuleLifecycle()

    def set_hooks(self, *, audit: Audit | None = None, broadcast: Broadcast | None = None) -> None:
        if audit is not None:
            self._audit = audit
        if broadcast is not None:
            self._bc = broadcast

    # ----- helpers -----------------------------------------------------------------
    async def _row(self, rule_id: str) -> RuleRow:
        row = await self._s.get(rule_id)
        if row is None or row.deleted:
            raise RuleError(404, "not_found", "That rule does not exist.")
        return row

    @staticmethod
    def _accounts(ir: dict[str, Any]) -> tuple[str, ...]:
        return tuple(str(a) for a in ir.get("scope", {}).get("account_ids", ()))

    def _visible(self, row: RuleRow, actor: Actor) -> bool:
        if not row.versions or actor.is_owner:
            return True
        accts = self._accounts(row.versions[-1].ir)
        return all(a in actor.granted_accounts for a in accts)

    def _require_grants(self, rule: Rule, actor: Actor) -> None:
        """C-12.4: a non-owner may only target accounts granted to them."""
        if actor.is_owner:
            return
        for a in rule.scope.account_ids:
            if str(a) not in actor.granted_accounts:
                raise RuleError(
                    403, "forbidden", "You do not have access to one of the accounts in scope."
                )

    async def _visible_row(self, rule_id: str, actor: Actor) -> RuleRow:
        row = await self._row(rule_id)
        if not self._visible(row, actor):
            raise RuleError(404, "not_found", "That rule does not exist.")
        return row

    def _view(self, row: RuleRow) -> dict[str, Any]:
        active = next((v for v in row.versions if v.id == row.active_version_id), None)
        out: dict[str, Any] = {
            "id": row.id,
            "name": row.name,
            "mode": row.mode,
            "scope": row.scope,
            "active_version_id": row.active_version_id,
            "latest_version": row.latest_version,
            "read_only": False,
        }
        if active is not None:
            bad = quarantine_path(active.ir)
            if bad is not None:
                self._metric("rule_quarantined_total", {})
                out.update(
                    read_only=True,
                    quarantined=True,
                    failing_path=bad,
                    export_json=copy.deepcopy(active.ir),
                    message=f"This rule is stored in a format the engine cannot read "
                    f"(problem at {bad}). It is read-only and disarmed. "
                    "Export it as JSON to repair it.",
                )
        return out

    async def _present(self, row: RuleRow) -> dict[str, Any]:
        """`_view` + a quarantine force-disarm recorded through the B9 chart (`DISARM`), so
        a corrupt rule is never left armed in the store or the engine."""
        active = next((v for v in row.versions if v.id == row.active_version_id), None)
        if row.mode == "armed" and active is not None and quarantine_path(active.ir):
            leaf = await self._leaf(row)
            payload = {"rule_id": row.id, "mode": "disabled", "from": row.mode}
            payload |= {"b9_from": leaf, "b9_event": "DISARM", "reason": "quarantined"}
            if await self._record_b9(row, "DISARM", "rule.disarmed", payload, reason="quarantined"):
                await self._bc({"topic": "rules", **payload})
        return self._view(row)

    @staticmethod
    def _version_view(v: VersionRow, full: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": v.id,
            "version": v.version,
            "ir_hash": v.ir_hash,
            "compiler_version": v.compiler_version,
            "notes": v.notes,
            "author": v.author,
        }
        if full:
            out["ir"] = copy.deepcopy(v.ir)
        return out

    def _validated(self, ir: dict[str, Any], rule_id: str) -> tuple[Rule, str]:
        try:
            rule = Rule.model_validate({**ir, "rule_id": rule_id})
        except ValidationError as exc:
            first = exc.errors()[0]
            raise RuleError(
                422,
                "rule_ir_invalid",
                f"The rule document is not valid: {first['msg']}",
                path="/" + "/".join(str(p) for p in first["loc"]),
            ) from exc
        res = validate_rule(rule, self._reg)
        if res.errors:
            raise RuleError(
                422,
                "rule_ir_invalid",
                res.errors[0].message,
                issues=[i.to_dict() for i in res.errors],
            )
        return rule, ir_hash(rule)

    def _new_version(
        self, row: RuleRow, rule: Rule, h: str, notes: str, actor: Actor
    ) -> VersionRow:
        row.latest_version += 1
        doc = {**rule.model_dump(mode="json"), "version": row.latest_version}
        v = VersionRow(
            str(uuid.uuid4()),
            row.id,
            row.latest_version,
            doc,
            h,
            COMPILER_VERSION,
            notes,
            actor.user_id,
            actor.session_id,
        )
        row.versions.append(v)
        row.last_editor, row.last_session = actor.user_id, actor.session_id
        self._metric("rule_versions_created_total", {})
        return v

    # ----- CRUD --------------------------------------------------------------------
    async def create(self, ir: dict[str, Any], actor: Actor, notes: str = "") -> dict[str, Any]:
        rid = str(uuid.uuid4())
        rule, h = self._validated({**ir, "mode": "disabled", "enabled": False}, rid)
        self._require_grants(rule, actor)
        existing = await self._s.all()
        if any(not r.deleted and r.name == rule.name for r in existing):
            raise RuleError(409, "name_taken", f"A rule named '{rule.name}' already exists.")
        row = RuleRow(rid, rule.name, actor.user_id, scope=rule.scope.level)
        v = self._new_version(row, rule, h, notes, actor)
        row.active_version_id = v.id
        await self._s.put(row)
        await self._audit(
            "rule.created", {"rule_id": rid, "version": 1, "ir_hash": h, "actor": actor.user_id}
        )
        return {**await self._present(row), "version": self._version_view(v)}

    async def list_rules(
        self,
        actor: Actor,
        mode: str | None = None,
        scope: str | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        everything = await self._s.all()
        rows = sorted(
            (r for r in everything if not r.deleted and self._visible(r, actor)),
            key=lambda r: r.id,
        )
        if mode:
            rows = [r for r in rows if r.mode == mode]
        if scope:
            rows = [r for r in rows if r.scope == scope]
        if cursor:
            rows = [r for r in rows if r.id > cursor]
        page = rows[:limit]
        return {
            "items": [await self._present(r) for r in page],
            "next_cursor": page[-1].id if len(rows) > limit else None,
        }

    async def get(self, rule_id: str, actor: Actor) -> dict[str, Any]:
        return await self._present(await self._visible_row(rule_id, actor))

    async def update(
        self,
        rule_id: str,
        ir: dict[str, Any],
        expected_version: int,
        actor: Actor,
        notes: str = "",
    ) -> dict[str, Any]:
        row = await self._visible_row(rule_id, actor)
        if expected_version != row.latest_version:
            self._metric("rule_save_conflicts_total", {})
            raise RuleError(
                409,
                "version_conflict",
                f"Another editor (session {row.last_session}) saved version "
                f"{row.latest_version} since you opened this rule. "
                "Reload it and reapply your changes.",
                conflicting_version=row.latest_version,
                author=row.last_editor,
                session=row.last_session,
                action="reload_and_reapply",
            )
        rule, h = self._validated(
            {**ir, "mode": row.mode, "enabled": row.mode != "disabled"}, rule_id
        )
        self._require_grants(rule, actor)
        existing = next((v for v in row.versions if v.ir_hash == h), None)
        if existing is not None:
            return {"created": False, "version": self._version_view(existing)}
        v = self._new_version(row, rule, h, notes, actor)
        row.name = rule.name
        await self._audit(
            "rule.updated",
            {"rule_id": rule_id, "version": v.version, "ir_hash": h, "actor": actor.user_id},
        )
        # A simulating/armed rule keeps running its previously active version (US-RULE-006).
        if row.mode == "disabled":
            row.active_version_id = v.id
        await self._s.put(row)
        return {"created": True, "version": self._version_view(v)}

    async def delete(self, rule_id: str, actor: Actor) -> None:
        row = await self._visible_row(rule_id, actor)
        if row.mode == "armed":
            raise RuleError(
                409,
                "conflict",
                "This rule is armed. Disarm it before deleting it; its history is kept.",
            )
        row.deleted = True  # soft delete; versions and runs retained
        await self._s.put(row)
        await self._audit("rule.deleted", {"rule_id": rule_id, "actor": actor.user_id})

    # ----- versions ----------------------------------------------------------------
    async def versions(self, rule_id: str) -> list[dict[str, Any]]:
        return [self._version_view(v) for v in reversed((await self._row(rule_id)).versions)]

    async def version(self, rule_id: str, version_id: str) -> dict[str, Any]:
        for v in (await self._row(rule_id)).versions:
            if v.id == version_id:
                return self._version_view(v, full=True)
        raise RuleError(404, "not_found", "That version does not exist.")

    async def set_active_version(
        self, rule_id: str, version_id: str, note: str, actor: Actor
    ) -> dict[str, Any]:
        row = await self._visible_row(rule_id, actor)
        v = next((x for x in row.versions if x.id == version_id), None)
        if v is None:
            raise RuleError(404, "not_found", "That version does not exist.")
        row.active_version_id = v.id
        demote = row.mode == "armed" and v.ir_hash not in row.simulated_hashes
        await self._audit(
            "rule.updated",
            {
                "rule_id": rule_id,
                "version": v.version,
                "ir_hash": v.ir_hash,
                "note": note,
                "actor": actor.user_id,
                "activated": True,
            },
        )
        if demote:
            # An unsimulated version must never run armed: B9 `armed --EDIT--> simulating`.
            leaf = await self._leaf(row)
            payload = {"rule_id": rule_id, "mode": "simulate", "from": "armed", "b9_from": leaf}
            payload |= {"b9_event": "EDIT", "actor": actor.user_id, "ir_hash": v.ir_hash}
            if not await self._record_b9(row, "EDIT", "rule.simulated", payload):
                raise RuleError(409, "conflict", "The rule could not leave armed. Disarm it first.")
            await self._bc({"topic": "rules", **payload})
        else:
            await self._s.put(row)
        return await self._present(row)

    async def record_simulation(self, rule_id: str, hash_: str, fires: int, hours: float) -> None:
        """Written by the simulation runner (E35-S05); consulted by the arming gate."""
        row = await self._row(rule_id)
        row.simulated_hashes.add(hash_)
        row.simulation_fires, row.simulation_hours = fires, hours
        await self._s.put(row)

    # ----- mode --------------------------------------------------------------------
    async def set_mode(
        self,
        rule_id: str,
        target: str,
        actor: Actor,
        idempotency_key: str | None,
        *,
        flatten_ack: bool = False,
        override_reason: str | None = None,
    ) -> dict[str, Any]:
        """Move a rule to *target* by sending the matching event to its B9 chart.

        Idempotency is state-based: a request for the mode the rule is already in is a
        200 no-op (no event, no audit, no broadcast), so a retried arm can never arm twice,
        also across restarts and workers. The bounded per-process cache only replays the
        first response byte-for-byte; it is keyed by actor and consulted after the RBAC
        visibility check, so another user's key never returns this user's result."""
        if not idempotency_key:
            raise RuleError(
                400,
                "idempotency_key_required",
                "Send an Idempotency-Key header so a retry cannot arm the rule twice.",
            )
        row = await self._visible_row(rule_id, actor)
        cache_key = f"{actor.user_id}:{rule_id}:{idempotency_key}:{target}"
        if cache_key in self._idem:
            self._idem.move_to_end(cache_key)
            return self._idem[cache_key]
        prev = row.mode
        try:
            out = await self._transition(row, target, actor, flatten_ack, override_reason)
        except RuleError as exc:
            self._metric(
                "rule_mode_transitions_total", {"from": prev, "to": target, "result": exc.code}
            )
            await self._audit(
                "rule.mode_refused",
                {"rule_id": rule_id, "from": prev, "to": target, "code": exc.code}
                | {"actor": actor.user_id},
            )
            raise
        self._idem[cache_key] = out
        while len(self._idem) > IDEM_CACHE_MAX:
            self._idem.popitem(last=False)
        return out

    async def _leaf(self, row: RuleRow) -> str:
        return await self.lifecycle.current(row.id, row.mode, row.disabled_reason)

    async def _record_b9(
        self, row: RuleRow, event: str, audit_action: str, payload: dict[str, Any], **ev: Any
    ) -> bool:
        """Send *event* to the rule's B9 chart (via the gateway) after the synchronous
        decision (C-2.21); if the chart moved, write the audit record (C-2.9, before/after)
        and only then persist the projected mode on the row. Returns False when the chart
        refused (nothing audited as a success, nothing persisted). Any failure after the
        chart moved evicts it, so it is rebuilt from the row - the durable truth - and the
        caller gets an error, never a 2xx."""
        try:
            before, leaf = await self.lifecycle.send(row.id, event, **ev)
        except LifecycleError as exc:
            await self.lifecycle.evict(row.id)
            raise RuleError(
                503, "lifecycle_unavailable", "Could not change the rule's mode. Try again."
            ) from exc
        if leaf == before:
            return False
        try:
            await self._audit(audit_action, payload | {"b9_to": leaf})
            row.mode = mode_of(leaf)
            row.disabled_reason = leaf if row.mode == "disabled" and leaf != "draft" else None
            row.armed_by = str(payload.get("actor") or row.owner) if row.mode == "armed" else None
            await self._s.put(row)
        except BaseException:
            await self.lifecycle.evict(row.id)
            raise
        return True

    async def _transition(
        self,
        row: RuleRow,
        target: str,
        actor: Actor,
        flatten_ack: bool,
        override_reason: str | None,
    ) -> dict[str, Any]:
        if target not in MODES:
            raise RuleError(
                422, "invalid_mode", f"Unknown mode '{target}'. Choose disabled, simulate or armed."
            )
        leaf = await self._leaf(row)
        prev = mode_of(leaf)
        if prev == target:
            return self._view(row)  # idempotent no-op: no event, no audit
        v = next((x for x in row.versions if x.id == row.active_version_id), None)
        if target in ("simulate", "armed") and (v is None or quarantine_path(v.ir)):
            raise RuleError(
                422,
                "rule_invalid",
                "This rule cannot be read by the engine. Export it and repair it first.",
            )
        ev_payload: dict[str, Any] = {"actor": actor.user_id}
        if target == "armed" and v is not None:
            ev_payload |= await self._check_arming(row, v, actor, flatten_ack, override_reason)
        event = await self.lifecycle.handled_event(
            row.id, row.mode, row.disabled_reason, target, **ev_payload
        )
        if event is None:
            raise RuleError(422, "illegal_transition", _illegal(leaf, target))
        if event == "HUMAN_REARM" or (target == "armed" and ev_payload.get("live")):
            await self._consume_step_up(actor)
        payload: dict[str, Any] = {
            "rule_id": row.id,
            "mode": target,
            "from": prev,
            "b9_from": leaf,
            "b9_event": event,
            "actor": actor.user_id,
        }
        if v is not None:
            scope = v.ir.get("scope", {})
            payload |= {
                "ir_hash": v.ir_hash,
                "version": v.version,
                "environments": list(scope.get("environments", [])),
                "scope": scope.get("level"),
            }
        if override_reason:
            payload["override_reason"] = override_reason
        action = {"armed": "rule.armed", "disabled": "rule.disarmed"}.get(target, "rule.simulated")
        if not await self._record_b9(row, event, action, payload, **ev_payload):
            raise RuleError(422, "illegal_transition", _illegal(leaf, target))
        self._metric("rule_mode_transitions_total", {"from": prev, "to": row.mode, "result": "ok"})
        await self._bc({"topic": "rules", **payload})  # emitted before the HTTP response returns
        return self._view(row)

    async def _consume_step_up(self, actor: Actor) -> None:
        # One-shot: a fresh code arms exactly one live / re-arm transition (no-grace class).
        if actor.consume_step_up is not None and not await actor.consume_step_up():
            raise RuleError(
                403, "step_up_required", "Re-enter your authenticator code to arm a live rule."
            )

    async def _check_arming(
        self,
        row: RuleRow,
        v: VersionRow,
        actor: Actor,
        flatten_ack: bool,
        override_reason: str | None,
    ) -> dict[str, Any]:
        """Synchronous arming decision (C-2.21). Raises on refusal; on success returns the
        server-computed facts the B9 guards read (`permitted` + simulation evidence)."""
        rule = Rule.model_validate(v.ir)
        res = validate_rule(rule, self._reg, actor.perms)
        types = {a.type for a in rule.actions}
        sims = v.ir_hash in row.simulated_hashes
        facts = ArmingFacts(
            has_valid_active_version=True,
            validation_errors=len(res.errors),
            open_safety_warnings=sum(1 for w in res.warnings if w.klass == "safety"),
            simulated_on_ir_hash=sims,
            simulation_fires=row.simulation_fires,
            simulation_hours=row.simulation_hours,
            environments=tuple(rule.scope.environments),
            sends_orders=bool(types & _ORDER_ACTIONS),
            has_flatten_all="flatten_all_positions" in types,
            perms=actor.perms,
            unauthorised_accounts=tuple(
                a
                for a in self._accounts(v.ir)
                if a not in actor.granted_accounts and not actor.is_owner
            ),
            step_up_fresh=actor.step_up_fresh,
            flatten_all_acknowledged=flatten_ack,
            owner_override_reason=override_reason,
            is_owner=actor.is_owner,
        )
        refusal = check_arming(facts)
        if refusal:
            raise RuleError(refusal.status, refusal.code, refusal.message)
        out: dict[str, Any] = {
            "permitted": True,
            "elevated": True,
            "is_owner": actor.is_owner,
            "simulation_fires": row.simulation_fires,
            "simulation_hours": row.simulation_hours,
            "live": "live" in facts.environments,
        }
        if override_reason:
            out["owner_override_reason"] = override_reason
        return out
