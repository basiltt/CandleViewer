"""Redactor (property-based over the SECRET registry), action registry,
and server-side RBAC for the /admin/audit* operations."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.audit.access import AuditAccessDenied, AuditPrincipal, authorize
from candleviewer.audit.actions import AUDIT_ACTIONS, UnknownAuditAction, validate_action
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.audit.redact import PII_HASH_PREFIX, REDACTION_MARKER, redact

_SECRET_KEYS = [
    "password_hash",
    "passwordHash",
    "totp_seed",
    "TOTP-SECRET",
    "recovery_codes",
    "refresh_token_hash",
    "invite_token",
    "api_key",
    "apiSecret",
    "signature",
]
_SENTINEL = "-".join(("sentinel", "value", "do-not-store"))


@given(
    key=st.sampled_from(_SECRET_KEYS),
    depth=st.integers(min_value=0, max_value=4),
    in_list=st.booleans(),
)
def test_redact_secret_never_survives_at_any_depth(key: str, depth: int, in_list: bool) -> None:
    node: Any = {key: _SENTINEL, "keep": 1}
    for _ in range(depth):
        node = {"nested": [node] if in_list else node}
    out = redact({"root": node})
    dumped = json.dumps(out)
    assert _SENTINEL not in dumped and REDACTION_MARKER in dumped


def test_redact_none_and_input_not_mutated() -> None:
    assert redact(None) is None
    plain = "p"
    src = {"password": plain, "list": [[{"x": 1}], 2]}
    out = redact(src)
    assert src["password"] is plain
    assert out == {"password": REDACTION_MARKER, "list": [[{"x": 1}], 2]}


def test_redact_pii_hashed_exact_names_only() -> None:
    out = redact({"email": "a@b.c", "ip": "1.2.3.4", "description": "d", "phone": None})
    assert out is not None
    assert out["email"].startswith(PII_HASH_PREFIX) and "a@b.c" not in out["email"]
    assert out["ip"].startswith(PII_HASH_PREFIX)
    assert out["description"] == "d" and out["phone"] is None


def test_actions_registry_accepts_known_rejects_unknown() -> None:
    assert validate_action("auth.login") == "auth.login"
    assert "admin.audit_denied" in AUDIT_ACTIONS
    with pytest.raises(UnknownAuditAction) as exc:
        validate_action("Auth.Login")
    assert exc.value.action == "Auth.Login"


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def emit(self, action: str, **kw: Any) -> None:
        self.calls.append((action, kw))


def _p(*perms: str) -> AuditPrincipal:
    return AuditPrincipal(
        user_id=uuid.uuid4(), username="u", permissions=frozenset(perms), ip="10.0.0.1"
    )


@pytest.mark.parametrize("op", ["query", "verify", "export"])
async def test_access_owner_allowed_everything(op: str) -> None:
    rec = _Recorder()
    await authorize(_p("*"), op, rec)
    assert rec.calls == []


MANAGER = (
    "orders:read",
    "orders:write",
    "accounts:read",
    "positions:read",
)


@pytest.mark.parametrize("op", ["query", "verify", "export"])
async def test_access_manager_denied_403_and_denial_audited(op: str) -> None:
    rec = _Recorder()
    principal = _p(*MANAGER)
    with pytest.raises(AuditAccessDenied):
        await authorize(principal, op, rec)
    [(action, kw)] = rec.calls
    assert action == "admin.audit_denied"
    assert kw["outcome"] is AuditOutcome.DENIED and kw["severity"] is Severity.WARNING
    assert kw["actor_user_id"] == principal.user_id


async def test_access_viewer_reads_but_cannot_export() -> None:
    rec = _Recorder()
    viewer = _p("audit:read")
    await authorize(viewer, "query", rec)
    await authorize(viewer, "verify", rec)
    with pytest.raises(AuditAccessDenied) as exc:
        await authorize(viewer, "export", rec)
    assert exc.value.permission == "audit:export"


async def test_access_manager_with_account_scope_still_cannot_read_other_accounts() -> None:
    """IDOR: audit read is scope `none` — an account-scoped manager permission
    set never grants any slice of the log, including rows about accounts it
    is not assigned to."""
    rec = _Recorder()
    with pytest.raises(AuditAccessDenied):
        await authorize(_p(*MANAGER, "accounts:write"), "query", rec)


async def test_access_unknown_operation_fails_closed() -> None:
    rec = _Recorder()
    with pytest.raises(AuditAccessDenied) as exc:
        await authorize(_p("*"), "delete", rec)
    assert exc.value.permission == "<unknown-operation>" and len(rec.calls) == 1
