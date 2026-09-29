"""Unit tests for `candleviewer.api.auth.make_auth_router` (E09-S01)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer.api.auth import make_auth_router
from candleviewer.auth.errors import AccountDisabled, AccountLocked, InvalidCredentials
from candleviewer.auth.models import LoginRequest, MfaChallengeResult, MfaMethodKind


class _FakeLoginService:
    def __init__(self, outcome: object) -> None:
        self._outcome = outcome

    async def login(self, request: LoginRequest, *, source_ip: str) -> MfaChallengeResult:
        if isinstance(self._outcome, Exception):
            raise self._outcome
        assert isinstance(self._outcome, MfaChallengeResult)
        return self._outcome


class _FakeAuthService:
    def __init__(self, outcome: object, *, active: bool = True) -> None:
        self._active = active
        self._login = _FakeLoginService(outcome)

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def login(self) -> _FakeLoginService:
        return self._login


def _app(outcome: object, *, active: bool = True) -> FastAPI:
    app = FastAPI()
    app.include_router(make_auth_router(_FakeAuthService(outcome, active=active)))
    return app


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
