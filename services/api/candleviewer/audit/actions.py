"""Typed action registry for `audit.emit` (M19, ticket "Scope / Deliverables":
"a typed action registry so `action` strings are not free-form at call sites").

The vocabulary below is the non-exhaustive list `docs/plan/21-database-schema.md`
Sec.3.10.1 enumerates as "actions that MUST be audited", plus the handful this
ticket's own acceptance criteria name explicitly (`admin.audit_denied` for the
non-owner-read-denial scenario, `admin.audit_read`/`admin.audit_verify`/
`admin.audit_export` for this module's own three endpoints). Every value
satisfies the migration's `au_action_fmt` CHECK
(`^[a-z0-9_]+([.][a-z0-9_]+){1,3}$`) — enforced here too so a typo'd literal
fails at call time (a clear `AuditError`) rather than at the INSERT.

Callers that need an action not yet in this registry add it here in the same
PR that starts calling `audit.emit` with it (single source of truth, C-16.5) —
never pass an ad-hoc string.
"""

from __future__ import annotations

import re

from candleviewer.audit.errors import AuditError

#: Mirrors the migration's `au_action_fmt` CHECK exactly.
_ACTION_FMT_RE = re.compile(r"^[a-z0-9_]+([.][a-z0-9_]+){1,3}$")

#: docs/plan/21-database-schema.md Sec.3.10.1 "Actions that MUST be audited"
#: plus this ticket's own admin.audit.* endpoints.
AUDIT_ACTIONS: frozenset[str] = frozenset(
    {
        "auth.login",
        "auth.login_failed",
        "auth.logout",
        "auth.refresh_reuse_detected",
        "auth.mfa_enroll",
        "auth.mfa_reset",
        "auth.password_change",
        "users.create",
        "users.disable",
        "roles.grant",
        "roles.revoke",
        "accounts.create",
        "accounts.enable_trading",
        "api_key.import",
        "api_key.rotate",
        "api_key.revoke",
        "api_key.reveal_attempt",
        "profiles.update",
        "orders.submit",
        "orders.cancel",
        "orders.amend",
        "trade_group.submit",
        "positions.flatten",
        "risk.freeze_manager",
        "risk.unfreeze_manager",
        "rules.arm",
        "rules.disarm",
        "rules.version_create",
        "alerts.create",
        "recorder.start",
        "recorder.stop",
        "retention.change",
        "retention.purge",
        "flags.change",
        "settings.change",
        "backup.run",
        "backup.restore",
        "env.switch_live",
        "admin.audit_read",
        "admin.audit_verify",
        "admin.audit_export",
        "admin.audit_denied",
    }
)

for _action in AUDIT_ACTIONS:
    if not _ACTION_FMT_RE.match(_action):  # pragma: no cover - defends the registry itself
        raise AuditError(f"registry action {_action!r} violates au_action_fmt")


def validate_action(action: str) -> str:
    """Return `action` unchanged if it is a registered, well-formed action.

    Raises `UnknownAuditAction` otherwise — `audit.emit` calls this before
    ever touching the WAL or a connection, so a typo'd call site fails fast
    and loudly rather than silently writing a malformed row that only the
    database CHECK would reject.
    """
    if action not in AUDIT_ACTIONS:
        raise UnknownAuditAction(action)
    return action


class UnknownAuditAction(AuditError):
    """Raised by `validate_action` when `action` is not in `AUDIT_ACTIONS`."""

    def __init__(self, action: str) -> None:
        super().__init__(
            f"{action!r} is not a registered audit action — add it to "
            "candleviewer.audit.actions.AUDIT_ACTIONS in the same PR that emits it"
        )
        self.action = action
