"""candleviewer.statechart.bindings.b16_session — guards/actions for B16
`session` (E09-S03, US-ONB-004/009).

Only `stamp_idle_deadline`/`set_revoke_*`/audit-adjacent actions and the
`mfa_attempts_exhausted` guard live here; the actual idle/absolute-lifetime
policy numbers (5-60 min configurable idle, 12 h absolute) are owned by
`candleviewer.auth.session_service.SessionService`, which drives this
machine via `REQUEST`/`IDLE_DEADLINE`/`ABSOLUTE_DEADLINE`/`REVOKE`/`LOGOUT`
events computed from the `sessions` row — this module never reads a clock
or a config value itself (CV-C-hot-path: statecharts record, synchronous
code enforces, C-2.21).

No service (`SERVICES`) is needed for B16 — every transition here is a
timer (`after:`, driven by the caller) or an externally-raised event, never
an invoked async operation.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from candleviewer.statechart.bindings import register_binding_module
from candleviewer.statechart.config import register_event_schemas

#: Ticket "Technical notes" / catalogue B16.4: five failed MFA attempts on
#: one session's `pending_mfa` leg locks it (mirrors `MfaService`'s own
#: `CHALLENGE_ATTEMPT_CAP`, but this is the *chart's* own attempt counter
#: in `context`, independent of the `mfa_challenges` row E09-S02 owns).
MFA_ATTEMPT_CAP = 5


def mfa_attempts_exhausted(context: dict[str, Any], event: dict[str, Any]) -> bool:
    """Guard: `context['mfa_attempts'] >= MFA_ATTEMPT_CAP`.

    Pure predicate, no I/O (B16.4 contract); total — returns `False` (never
    raises) on any malformed context, per catalogue A6 ("no I/O; total;
    returns False on any internal error and logs at ERROR")."""
    try:
        attempts = context.get("mfa_attempts", 0)
        return bool(int(attempts) >= MFA_ATTEMPT_CAP)
    except (TypeError, ValueError):
        return False


async def mark_mfa_satisfied(context: dict[str, Any], event: dict[str, Any]) -> None:
    context["mfa_satisfied"] = True


async def bump_mfa_attempts(context: dict[str, Any], event: dict[str, Any]) -> None:
    context["mfa_attempts"] = int(context.get("mfa_attempts", 0)) + 1


async def audit_mfa_failed(context: dict[str, Any], event: dict[str, Any]) -> None:
    """Audit emission is the caller's responsibility in every other M18
    module (`forbidden-M18`: `auth`/`statechart` may not import `audit`
    directly); this action is a no-op placeholder the audit plugin
    (`CvAuditPlugin`, E50-T60) observes via the interpreter's own action
    trace rather than a direct call out of this binding."""
    return None


async def set_revoke_locked(context: dict[str, Any], event: dict[str, Any]) -> None:
    context["revoke_reason"] = "locked"


async def set_revoke_timeout(context: dict[str, Any], event: dict[str, Any]) -> None:
    context["revoke_reason"] = "timeout"


async def set_revoke_idle(context: dict[str, Any], event: dict[str, Any]) -> None:
    context["revoke_reason"] = "idle"


async def set_revoke_expired(context: dict[str, Any], event: dict[str, Any]) -> None:
    context["revoke_reason"] = "expired"


async def set_revoke_admin(context: dict[str, Any], event: dict[str, Any]) -> None:
    context["revoke_reason"] = "admin"


async def set_revoke_logout(context: dict[str, Any], event: dict[str, Any]) -> None:
    context["revoke_reason"] = "logout"


async def stamp_idle_deadline(context: dict[str, Any], event: dict[str, Any]) -> None:
    """Re-stamped on every `REQUEST` (ticket "idle timeout ... driven by
    `sessions.last_seen_at`") — the deadline value itself is computed by
    the caller and carried on the event payload (`event['idle_expires_at_
    us']`), never derived from a clock read in this binding."""
    idle_expires_at_us = event.get("idle_expires_at_us")
    if idle_expires_at_us is not None:
        context["idle_expires_at_us"] = idle_expires_at_us


async def audit_login(context: dict[str, Any], event: dict[str, Any]) -> None:
    return None


async def audit_session_revoked(context: dict[str, Any], event: dict[str, Any]) -> None:
    return None


async def broadcast_revocation(context: dict[str, Any], event: dict[str, Any]) -> None:
    """Placeholder for the WS revocation-frame publish (E17 owns the
    transport itself; this action only marks that the chart reached the
    terminal `revoked` state so `SessionService` can react to the
    interpreter's state-entry notification, per this ticket's "Out of
    scope: the WS transport implementation itself")."""
    return None


async def stamp_elevated_until(context: dict[str, Any], event: dict[str, Any]) -> None:
    elevated_until_us = event.get("elevated_until_us")
    if elevated_until_us is not None:
        context["elevated_until_us"] = elevated_until_us


async def audit_step_up(context: dict[str, Any], event: dict[str, Any]) -> None:
    return None


async def audit_step_up_failed(context: dict[str, Any], event: dict[str, Any]) -> None:
    return None


async def clear_elevated(context: dict[str, Any], event: dict[str, Any]) -> None:
    context["elevated_until_us"] = None


async def schedule_elevation_deadline(context: dict[str, Any], event: dict[str, Any]) -> None:
    return None


ACTIONS: dict[str, Callable[..., Awaitable[None]]] = {
    "mark_mfa_satisfied": mark_mfa_satisfied,
    "bump_mfa_attempts": bump_mfa_attempts,
    "audit_mfa_failed": audit_mfa_failed,
    "set_revoke_locked": set_revoke_locked,
    "set_revoke_timeout": set_revoke_timeout,
    "set_revoke_idle": set_revoke_idle,
    "set_revoke_expired": set_revoke_expired,
    "set_revoke_admin": set_revoke_admin,
    "set_revoke_logout": set_revoke_logout,
    "stamp_idle_deadline": stamp_idle_deadline,
    "audit_login": audit_login,
    "audit_session_revoked": audit_session_revoked,
    "broadcast_revocation": broadcast_revocation,
    "stamp_elevated_until": stamp_elevated_until,
    "audit_step_up": audit_step_up,
    "audit_step_up_failed": audit_step_up_failed,
    "clear_elevated": clear_elevated,
    "schedule_elevation_deadline": schedule_elevation_deadline,
}

GUARDS: dict[str, Callable[..., bool]] = {
    "mfa_attempts_exhausted": mfa_attempts_exhausted,
}

SERVICES: dict[str, Callable[..., Awaitable[Any]]] = {}

register_binding_module("session", __name__)

#: B16 events this ticket owns (CV-C-strict: `strict=True` refuses any
#: event with no schema entry here). Minimal shape — `type` is always
#: implied by the dict key the library indexes on; these are the payload
#: fields each event may carry, all optional so a bare `{"type": "..."}`
#: event (e.g. `LOGOUT`, `REVOKE`) still validates.
register_event_schemas(
    {
        "MFA_OK": {"type": "object", "additionalProperties": True},
        "MFA_FAILED": {"type": "object", "additionalProperties": True},
        "MFA_TIMEOUT": {"type": "object", "additionalProperties": True},
        "REQUEST": {"type": "object", "additionalProperties": True},
        "IDLE_DEADLINE": {"type": "object", "additionalProperties": True},
        "ABSOLUTE_DEADLINE": {"type": "object", "additionalProperties": True},
        "REVOKE": {"type": "object", "additionalProperties": True},
        "LOGOUT": {"type": "object", "additionalProperties": True},
        "STEP_UP_OK": {"type": "object", "additionalProperties": True},
        "STEP_UP_FAILED": {"type": "object", "additionalProperties": True},
        "ELEVATION_DEADLINE": {"type": "object", "additionalProperties": True},
    }
)
