"""Unit tests for `candleviewer.api.auth.make_auth_router` (E09-S01)."""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer.api.auth import make_auth_router
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.errors import (
    AccountDisabled,
    AccountLocked,
    InvalidCredentials,
    MfaChallengeInvalid,
    RecoveryCodesExhausted,
)
from candleviewer.auth.models import (
    LoginRequest,
    MfaChallengeResult,
    MfaEnrollRequest,
    MfaEnrollResult,
    MfaMethodKind,
    MfaVerifiedResult,
    MfaVerifyRequest,
)


class _FakeLoginService:
    def __init__(self, outcome: object) -> None:
        self._outcome = outcome

    async def login(self, request: LoginRequest, *, source_ip: str) -> MfaChallengeResult:
        if isinstance(self._outcome, Exception):
            raise self._outcome
        assert isinstance(self._outcome, MfaChallengeResult)
        return self._outcome


class _FakeMfaService:
    def __init__(self, outcome: object) -> None:
        self._outcome = outcome

    def _resolve(self) -> object:
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome

    async def verify(self, request: MfaVerifyRequest) -> MfaVerifiedResult:
        result = self._resolve()
        assert isinstance(result, MfaVerifiedResult)
        return result

    async def enroll(
        self, user_id: str, request: MfaEnrollRequest, *, account_name: str
    ) -> MfaEnrollResult:
        result = self._resolve()
        assert isinstance(result, MfaEnrollResult)
        return result

    async def confirm_enrollment(
        self, user_id: str, *, method_id: str, code: str
    ) -> tuple[MfaMethodKind, tuple[str, ...]]:
        result = self._resolve()
        assert isinstance(result, tuple)
        return result

    async def recover(self, mfa_token: str, recovery_code: str) -> MfaVerifiedResult:
        result = self._resolve()
        assert isinstance(result, MfaVerifiedResult)
        return result


class _FakeAuthService:
    def __init__(
        self,
        outcome: object,
        *,
        active: bool = True,
        mfa_outcome: object = None,
        mfa_active: bool = True,
    ) -> None:
        self._active = active
        self._login = _FakeLoginService(outcome)
        self._mfa_active = mfa_active
        self._mfa = _FakeMfaService(mfa_outcome)

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def login(self) -> _FakeLoginService:
        return self._login

    @property
    def mfa_is_active(self) -> bool:
        return self._mfa_active

    @property
    def mfa(self) -> _FakeMfaService:
        return self._mfa


def _app(outcome: object, *, active: bool = True) -> FastAPI:
    app = FastAPI()
    app.include_router(make_auth_router(_FakeAuthService(outcome, active=active)))
    return app


def _mfa_app(
    mfa_outcome: object, *, mfa_active: bool = True, audit_service: object = None
) -> FastAPI:
    app = FastAPI()
    app.include_router(
        make_auth_router(
            _FakeAuthService(
                InvalidCredentials("n/a"), mfa_outcome=mfa_outcome, mfa_active=mfa_active
            ),
            audit_service=audit_service,  # type: ignore[arg-type]
        )
    )
    return app


class _RecordingAuditWriter:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def emit(
        self,
        action: str,
        *,
        actor_label: str,
        actor_ip: str | None = None,
        outcome: AuditOutcome = AuditOutcome.SUCCESS,
        severity: Severity = Severity.INFO,
    ) -> None:
        self.calls.append(
            {
                "action": action,
                "actor_label": actor_label,
                "actor_ip": actor_ip,
                "outcome": outcome,
                "severity": severity,
            }
        )


class _RecordingAuditService:
    def __init__(self) -> None:
        self.writer = _RecordingAuditWriter()

    @property
    def is_active(self) -> bool:
        return True


def test_successful_login_returns_mfa_challenge() -> None:
    client = TestClient(
        _app(MfaChallengeResult(mfa_token="tok", methods=(MfaMethodKind.TOTP,), expires_in=300))
    )
    response = client.post("/auth/login", json={"identifier": "basiltt", "password": "x"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "mfa_required"
    assert body["mfa_token"] == "tok"
    assert body["methods"] == ["totp"]


def test_invalid_credentials_returns_401_problem_json() -> None:
    client = TestClient(_app(InvalidCredentials("Username or password is incorrect")))
    response = client.post("/auth/login", json={"identifier": "basiltt", "password": "x"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Username or password is incorrect"


def test_account_disabled_returns_403() -> None:
    client = TestClient(_app(AccountDisabled("Account disabled - contact the owner")))
    response = client.post("/auth/login", json={"identifier": "basiltt", "password": "x"})
    assert response.status_code == 403


def test_account_locked_returns_423_with_retry_after_header() -> None:
    client = TestClient(_app(AccountLocked(600)))
    response = client.post("/auth/login", json={"identifier": "basiltt", "password": "x"})
    assert response.status_code == 423
    assert response.headers["Retry-After"] == "600"


def test_inactive_auth_service_returns_503() -> None:
    client = TestClient(_app(InvalidCredentials("n/a"), active=False))
    response = client.post("/auth/login", json={"identifier": "basiltt", "password": "x"})
    assert response.status_code == 503


def test_account_locked_emits_auth_account_locked_audit_action_with_warning_severity() -> None:
    """Regression for QA bug #1604 defect 2: the ticket's Scope / Deliverables
    names `auth.account_locked` (severity warning) as the lockout audit
    action; the router must not reuse `auth.login_failed` for this path."""
    audit_service = _RecordingAuditService()
    app = FastAPI()
    app.include_router(
        make_auth_router(_FakeAuthService(AccountLocked(600)), audit_service=audit_service)
    )
    client = TestClient(app)

    response = client.post("/auth/login", json={"identifier": "basiltt", "password": "x"})

    assert response.status_code == 423
    assert len(audit_service.writer.calls) == 1
    call = audit_service.writer.calls[0]
    assert call["action"] == "auth.account_locked"
    assert call["outcome"] == AuditOutcome.DENIED
    assert call["severity"] == Severity.WARNING


# -- /auth/mfa/verify ------------------------------------------------------


def test_mfa_verify_success_returns_authenticated() -> None:
    client = TestClient(_mfa_app(MfaVerifiedResult(user_id=uuid.uuid4())))
    response = client.post(
        "/auth/mfa/verify", json={"mfa_token": "tok", "method": "totp", "code": "123456"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "authenticated"


def test_mfa_verify_invalid_code_returns_401_and_audits_failure() -> None:
    audit_service = _RecordingAuditService()
    client = TestClient(
        _mfa_app(MfaChallengeInvalid("no open challenge"), audit_service=audit_service)
    )
    response = client.post(
        "/auth/mfa/verify", json={"mfa_token": "tok", "method": "totp", "code": "123456"}
    )
    assert response.status_code == 401
    assert audit_service.writer.calls[0]["action"] == "auth.mfa_failed"


def test_mfa_verify_inactive_backend_returns_503() -> None:
    client = TestClient(_mfa_app(MfaVerifiedResult(user_id=uuid.uuid4()), mfa_active=False))
    response = client.post(
        "/auth/mfa/verify", json={"mfa_token": "tok", "method": "totp", "code": "123456"}
    )
    assert response.status_code == 503


# -- /auth/mfa/recovery ------------------------------------------------------


def test_mfa_recovery_success_returns_authenticated_and_forced_reenroll() -> None:
    client = TestClient(
        _mfa_app(MfaVerifiedResult(user_id=uuid.uuid4(), forced_totp_reenroll=True))
    )
    response = client.post(
        "/auth/mfa/recovery", json={"mfa_token": "tok", "recovery_code": "7F2A-91BC-4DE0"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "authenticated"
    assert body["forced_totp_reenroll"] is True


def test_mfa_recovery_exhausted_returns_401_and_audits_denied() -> None:
    audit_service = _RecordingAuditService()
    client = TestClient(_mfa_app(RecoveryCodesExhausted("all used"), audit_service=audit_service))
    response = client.post(
        "/auth/mfa/recovery", json={"mfa_token": "tok", "recovery_code": "7F2A-91BC-4DE0"}
    )
    assert response.status_code == 401
    call = audit_service.writer.calls[0]
    assert call["action"] == "auth.recovery_codes_exhausted"
    assert call["outcome"] == AuditOutcome.DENIED


# -- /auth/mfa/enroll --------------------------------------------------------
# PR #1618 review finding 1: enrolment is disabled (`501`) until E09-S03
# wires real session/principal resolution — trusting the client-supplied
# `X-User-Id`/`X-Username` headers with no verification would let anyone
# enrol (and read the one-time recovery codes for) any account.


def test_mfa_enroll_disabled_returns_501_regardless_of_headers() -> None:
    method_id = uuid.uuid4()
    client = TestClient(
        _mfa_app(
            MfaEnrollResult(
                method_id=method_id,
                method=MfaMethodKind.TOTP,
                otpauth_uri="otpauth://totp/x",
                secret_base32="ABC",
            )
        )
    )
    response = client.post(
        "/auth/mfa/enroll",
        json={"method": "totp", "label": "phone"},
        headers={"X-User-Id": str(uuid.uuid4()), "X-Username": "alice"},
    )
    assert response.status_code == 501


def test_mfa_enroll_disabled_even_without_headers() -> None:
    client = TestClient(_mfa_app(None))
    response = client.post("/auth/mfa/enroll", json={"method": "totp", "label": "phone"})
    assert response.status_code == 501


# -- /auth/mfa/enroll/confirm -------------------------------------------------
# Same rationale as `/auth/mfa/enroll` above.


def test_mfa_enroll_confirm_disabled_returns_501_regardless_of_headers() -> None:
    client = TestClient(_mfa_app((MfaMethodKind.TOTP, ("7F2A-91BC-4DE0",))))
    response = client.post(
        "/auth/mfa/enroll/confirm",
        json={"method_id": str(uuid.uuid4()), "code": "123456"},
        headers={"X-User-Id": str(uuid.uuid4())},
    )
    assert response.status_code == 501


def test_mfa_enroll_confirm_disabled_even_without_headers() -> None:
    client = TestClient(_mfa_app(None))
    response = client.post(
        "/auth/mfa/enroll/confirm", json={"method_id": str(uuid.uuid4()), "code": "123456"}
    )
    assert response.status_code == 501
