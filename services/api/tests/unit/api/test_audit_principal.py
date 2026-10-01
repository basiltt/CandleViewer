"""QA #1596: session-backed principal resolver + HTTP RBAC (401 / 403 / 200)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer.api.audit import make_audit_router
from candleviewer.api.audit_principal import SessionAuditPrincipalResolver
from candleviewer.auth.errors import SessionNotFound
from tests.unit.api.test_audit_router import _FakeAuditService

_OWNER = uuid.uuid4()
_MANAGER = uuid.uuid4()


class _Sessions:
    async def authenticate_access_token(self, token: str, *, touch: bool = False) -> Any:
        users = {"owner-tok": _OWNER, "mgr-tok": _MANAGER}
        if token not in users:
            raise SessionNotFound("nope")
        return SimpleNamespace(id=uuid.uuid4(), user_id=users[token])


class _Identity:
    async def user(self, user_id: str) -> dict[str, Any]:
        owner = user_id == str(_OWNER)
        return {"username": "o" if owner else "m", "status": "active"}

    async def session_info(self, user_id: str) -> dict[str, Any]:
        return {"permissions": ["*"] if user_id == str(_OWNER) else ["accounts:read"]}


def _client() -> tuple[TestClient, _FakeAuditService]:
    svc = _FakeAuditService()
    app = FastAPI()
    resolver = SessionAuditPrincipalResolver(lambda: _Sessions(), _Identity())
    app.include_router(make_audit_router(svc, resolver))
    return TestClient(app), svc


def test_audit_query_without_token_is_401() -> None:
    client, _ = _client()
    assert client.get("/admin/audit").status_code == 401


def test_audit_query_unknown_token_is_401() -> None:
    client, _ = _client()
    r = client.get("/admin/audit", headers={"Authorization": "Bearer bad"})
    assert r.status_code == 401


def test_audit_query_manager_is_403_and_denial_audited() -> None:
    client, svc = _client()
    r = client.get("/admin/audit", headers={"Authorization": "Bearer mgr-tok"})
    assert r.status_code == 403
    assert svc.writer_service.emitted[0][0] == "admin.audit_denied"


def test_audit_query_owner_is_200() -> None:
    client, _ = _client()
    r = client.get("/admin/audit", headers={"Authorization": "Bearer owner-tok"})
    assert r.status_code == 200
