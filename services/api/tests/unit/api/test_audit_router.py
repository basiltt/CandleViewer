"""Unit tests for `candleviewer.api.audit.make_audit_router` (QA defect
#1596: "No HTTP router wired for /admin/audit, /admin/audit/verify,
/admin/audit/export"). Regression: `grep -rn 'APIRouter'
services/api/candleviewer/audit` found nothing before this fix, and none of
these routes existed on `create_app()`'s FastAPI instance."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api.audit import make_audit_router
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.models import AuditPage, ExportResult, VerifyResult


class _FakeQuery:
    def __init__(self) -> None:
        self.query_calls: list[dict[str, Any]] = []
        self.verify_calls: list[dict[str, Any]] = []
        self.export_calls: list[dict[str, Any]] = []

    async def query(self, **kwargs: Any) -> AuditPage:
        self.query_calls.append(kwargs)
        return AuditPage(items=[], chain_verified=True, count=0)

    async def verify(self, **kwargs: Any) -> VerifyResult:
        self.verify_calls.append(kwargs)
        return VerifyResult(
            verified=True, entries_checked=0, first_bad_id=None, checked_at=datetime.now(UTC)
        )

    async def schedule_export(self, **kwargs: Any) -> ExportResult:
        self.export_calls.append(kwargs)
        return ExportResult(job_id=uuid.uuid4(), download_url=None)


class _FakeWriter:
    def __init__(self) -> None:
        self.emitted: list[tuple[str, dict[str, Any]]] = []

    async def emit(self, action: str, **kwargs: Any) -> None:
        self.emitted.append((action, kwargs))


class _FakeAuditService:
    def __init__(self, *, active: bool = True) -> None:
        self._active = active
        self.query_service = _FakeQuery()
        self.writer_service = _FakeWriter()

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def query(self) -> _FakeQuery:
        return self.query_service

    @property
    def writer(self) -> _FakeWriter:
        return self.writer_service


class _FakeResolver:
    def __init__(self, principal: AuditPrincipal | None) -> None:
        self._principal = principal

    def resolve(self, request: Request) -> AuditPrincipal | None:
        return self._principal


def _owner() -> AuditPrincipal:
    return AuditPrincipal(user_id=uuid.uuid4(), username="owner", permissions=frozenset({"*"}))


def _viewer_no_export() -> AuditPrincipal:
    return AuditPrincipal(
        user_id=uuid.uuid4(), username="viewer", permissions=frozenset({"audit:read"})
    )


def _manager() -> AuditPrincipal:
    return AuditPrincipal(
        user_id=uuid.uuid4(), username="manager", permissions=frozenset({"orders:read"})
    )


def _app(audit_service: _FakeAuditService | None, resolver: _FakeResolver | None) -> FastAPI:
    app = FastAPI()
    app.include_router(make_audit_router(audit_service, resolver))
    return app


def test_query_audit_log_returns_200_for_authorized_owner() -> None:
    service = _FakeAuditService()
    client = TestClient(_app(service, _FakeResolver(_owner())))
    response = client.get("/admin/audit")
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["chain_verified"] is True
    assert len(service.query_service.query_calls) == 1


def test_query_audit_log_denied_for_manager_returns_403_and_audits_denial() -> None:
    service = _FakeAuditService()
    client = TestClient(_app(service, _FakeResolver(_manager())))
    response = client.get("/admin/audit")
    assert response.status_code == 403
    [(action, kwargs)] = service.writer_service.emitted
    assert action == "admin.audit_denied"
    assert kwargs["outcome"].value == "denied"


def test_verify_audit_chain_returns_200_for_authorized_caller() -> None:
    service = _FakeAuditService()
    client = TestClient(_app(service, _FakeResolver(_owner())))
    response = client.post("/admin/audit/verify", json={})
    assert response.status_code == 200
    assert response.json()["verified"] is True
    assert len(service.query_service.verify_calls) == 1


def test_export_audit_log_returns_202_for_authorized_owner() -> None:
    service = _FakeAuditService()
    client = TestClient(_app(service, _FakeResolver(_owner())))
    response = client.post(
        "/admin/audit/export",
        json={"from": "2026-01-01T00:00:00Z", "to": "2026-01-02T00:00:00Z"},
    )
    assert response.status_code == 202
    assert "job_id" in response.json()
    assert len(service.query_service.export_calls) == 1


def test_export_audit_log_denied_for_read_only_viewer() -> None:
    service = _FakeAuditService()
    client = TestClient(_app(service, _FakeResolver(_viewer_no_export())))
    response = client.post(
        "/admin/audit/export",
        json={"from": "2026-01-01T00:00:00Z", "to": "2026-01-02T00:00:00Z"},
    )
    assert response.status_code == 403


def test_inactive_audit_service_returns_503() -> None:
    service = _FakeAuditService(active=False)
    client = TestClient(_app(service, _FakeResolver(_owner())))
    response = client.get("/admin/audit")
    assert response.status_code == 503


def test_no_principal_resolver_wired_returns_501_not_implemented() -> None:
    service = _FakeAuditService()
    client = TestClient(_app(service, None))
    response = client.get("/admin/audit")
    assert response.status_code == 501


def test_no_audit_service_wired_returns_503() -> None:
    client = TestClient(_app(None, _FakeResolver(_owner())))
    response = client.get("/admin/audit")
    assert response.status_code == 503


def test_resolver_returning_none_returns_401_unauthorized() -> None:
    """PR #1608 review finding 4: a *wired* resolver reporting "no verified
    session" is 401, distinct from the "nothing wired at all" 501 case."""
    service = _FakeAuditService()
    client = TestClient(_app(service, _FakeResolver(None)))
    response = client.get("/admin/audit")
    assert response.status_code == 401


def test_query_audit_log_passes_subject_type_through_to_query_service() -> None:
    """PR #1608 review finding 5: `subject_type` used to be accepted and
    silently dropped."""
    service = _FakeAuditService()
    client = TestClient(_app(service, _FakeResolver(_owner())))
    response = client.get("/admin/audit", params={"subject_type": "order"})
    assert response.status_code == 200
    [call] = service.query_service.query_calls
    assert call["subject_type"] == "order"


def test_verify_audit_chain_rejects_unknown_body_field() -> None:
    service = _FakeAuditService()
    client = TestClient(_app(service, _FakeResolver(_owner())))
    response = client.post("/admin/audit/verify", json={"unexpected": "x"})
    assert response.status_code == 400


def test_verify_audit_chain_rejects_from_id_greater_than_to_id() -> None:
    service = _FakeAuditService()
    client = TestClient(_app(service, _FakeResolver(_owner())))
    response = client.post("/admin/audit/verify", json={"from_id": 10, "to_id": 5})
    assert response.status_code == 400


def test_verify_audit_chain_rejects_non_integer_from_id() -> None:
    service = _FakeAuditService()
    client = TestClient(_app(service, _FakeResolver(_owner())))
    response = client.post("/admin/audit/verify", json={"from_id": "not-an-id"})
    assert response.status_code == 400


def test_export_audit_log_rejects_malformed_timestamp_with_400_not_500() -> None:
    """PR #1608 review finding 3: a bad `from`/`to` string used to reach
    `_parse_ts` and raise an unhandled `ValueError` (500)."""
    service = _FakeAuditService()
    client = TestClient(_app(service, _FakeResolver(_owner())))
    response = client.post(
        "/admin/audit/export", json={"from": "not-a-timestamp", "to": "2026-01-02T00:00:00Z"}
    )
    assert response.status_code == 400


def test_export_audit_log_rejects_naive_datetime() -> None:
    service = _FakeAuditService()
    client = TestClient(_app(service, _FakeResolver(_owner())))
    response = client.post(
        "/admin/audit/export",
        json={"from": "2026-01-01T00:00:00", "to": "2026-01-02T00:00:00"},
    )
    assert response.status_code == 400


def test_export_audit_log_rejects_from_after_to() -> None:
    service = _FakeAuditService()
    client = TestClient(_app(service, _FakeResolver(_owner())))
    response = client.post(
        "/admin/audit/export",
        json={"from": "2026-01-02T00:00:00Z", "to": "2026-01-01T00:00:00Z"},
    )
    assert response.status_code == 400


def test_export_audit_log_rejects_missing_from() -> None:
    service = _FakeAuditService()
    client = TestClient(_app(service, _FakeResolver(_owner())))
    response = client.post("/admin/audit/export", json={"to": "2026-01-02T00:00:00Z"})
    assert response.status_code == 400
