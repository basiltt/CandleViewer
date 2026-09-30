"""Unit tests for `candleviewer.auth.service.AuthService` (E09-S01).

Regression for QA bug #1604 defect 1: `candleviewer/auth/*` was still in the
coverage omit list after the real `AuthService.start()`/`login` wiring
landed, so `service.py` (and the rest of the module) sat at 0% covered
without failing the 85% floor. This test exercises the lifecycle directly:
before `start()`, after `start()` with no repository (scaffold), after
`start()` with a real repository (wired), and `stop()`."""

from __future__ import annotations

import pytest

from candleviewer.auth.service import AuthService
from candleviewer.observability.health import HealthStatus
from tests.unit.auth.auth_fakes import FakeUserRepository
from tests.unit.auth.mfa_fakes import FakeMfaRepository


def test_auth_service_before_start_is_inactive_and_stopped() -> None:
    service = AuthService()

    assert service.is_active is False
    report = service.health()
    assert report.status is HealthStatus.STOPPED
    assert report.module == "auth"


async def test_auth_service_start_without_repository_stays_scaffold() -> None:
    service = AuthService()

    await service.start(ctx=None)  # type: ignore[arg-type]

    assert service.is_active is False
    report = service.health()
    assert report.status is HealthStatus.OK
    assert "no repository wired" in report.detail
    with pytest.raises(RuntimeError, match="has not wired a real backend"):
        _ = service.login


async def test_auth_service_start_with_repository_wires_login_service() -> None:
    service = AuthService(repository=FakeUserRepository(), pepper="pepper")

    await service.start(ctx=None)  # type: ignore[arg-type]

    assert service.is_active is True
    report = service.health()
    assert report.status is HealthStatus.OK
    assert report.detail == ""
    assert service.login is not None


async def test_auth_service_stop_clears_login_and_marks_stopped() -> None:
    service = AuthService(repository=FakeUserRepository(), pepper="pepper")
    await service.start(ctx=None)  # type: ignore[arg-type]

    await service.stop(grace_s=1.0)

    assert service.is_active is False
    assert service.health().status is HealthStatus.STOPPED


async def test_auth_service_start_without_mfa_repository_stays_scaffold() -> None:
    service = AuthService()

    await service.start(ctx=None)  # type: ignore[arg-type]

    assert service.mfa_is_active is False
    with pytest.raises(RuntimeError, match="has not wired an MfaRepository"):
        _ = service.mfa


async def test_auth_service_start_with_mfa_repository_wires_mfa_service() -> None:
    service = AuthService(mfa_repository=FakeMfaRepository(), totp_encryption_key=b"0" * 32)

    await service.start(ctx=None)  # type: ignore[arg-type]

    assert service.mfa_is_active is True
    assert service.mfa is not None


async def test_auth_service_stop_clears_mfa_and_marks_inactive() -> None:
    service = AuthService(mfa_repository=FakeMfaRepository(), totp_encryption_key=b"0" * 32)
    await service.start(ctx=None)  # type: ignore[arg-type]

    await service.stop(grace_s=1.0)

    assert service.mfa_is_active is False
