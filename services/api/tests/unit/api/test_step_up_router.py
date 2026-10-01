"""HTTP-level E09-S04 tests: step-up, no-grace, read-only guard, owner reset, audit."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api.step_up import make_read_only_guard, make_step_up_router
from candleviewer.audit.models import Severity
from candleviewer.auth.envelope import TotpEncryptor
from candleviewer.auth.errors import SessionNotFound
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.mfa_service import MfaService
from candleviewer.auth.models import MfaEnrollRequest, MfaMethodKind, SessionRecord
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.auth.step_up import StepUpService
from candleviewer.auth.totp import generate_code, time_step_for
from tests.unit.auth.mfa_fakes import FakeMfaRepository
from tests.unit.auth.session_fakes import FakeSessionRepository

_T0 = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)


class _Clock:
    now = _T0

    def __call__(self) -> datetime:
        return self.now


class _Emitter:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def emit(self, action: str, **kw: Any) -> None:
        self.calls.append({"action": action, **kw})

    def actions(self) -> list[str]:
        return [c["action"] for c in self.calls]


class _Sessions:
    def __init__(self, records: dict[str, SessionRecord]) -> None:
        self.records = records

    async def authenticate_access_token(self, token: str) -> SessionRecord:
        if token not in self.records:
            raise SessionNotFound("x")
        return self.records[token]


class _Auth:
    step_up_is_active = True
    sessions_is_active = True

    def __init__(self, step_up: StepUpService, sessions: _Sessions) -> None:
        self.step_up = step_up
        self.sessions = sessions


class _Resolver:
    def __init__(self, snap: PrincipalSnapshot) -> None:
        self.snap = snap

    def resolve(self, request: Request) -> PrincipalSnapshot | None:
        return self.snap


class _Positions:
    source = "oms"

    async def open_position_count(self, user_id: str) -> int | None:
        return 2


class _NoStore:
    source = "not_deployed"

    async def open_position_count(self, user_id: str) -> int | None:
        return None


def _record(user: uuid.UUID) -> SessionRecord:
    return SessionRecord(
        id=uuid.uuid4(), user_id=user, refresh_token_hash="h", access_token_jti=None,  # noqa: S106
       
        issued_at=_T0, last_seen_at=_T0, expires_at=_T0 + timedelta(days=1), revoked_at=None,
        revoked_reason=None, ip=None, user_agent=None, device_label=None, is_electron=False,
        mfa_satisfied_at=None,
    )  # fmt: skip


async def _build(
    owner_role: bool = True, positions: Any = None
) -> tuple[TestClient, _Emitter, bytes, _Clock, uuid.UUID]:
    clock, repo, enc = _Clock(), FakeMfaRepository(), TotpEncryptor(os.urandom(32))
    mfa = MfaService(repo, enc, recovery_code_key=b"k" * 32, clock=clock)
    user = uuid.uuid4()
    res = await mfa.enroll(
        str(user), MfaEnrollRequest(method=MfaMethodKind.TOTP, label=""), account_name="o"
    )
    seed = enc.decrypt(repo.methods[str(res.method_id)].secret_enc)  # type: ignore[arg-type]
    await mfa.confirm_enrollment(
        str(user), method_id=str(res.method_id),
        code=generate_code(seed, time_step_for(_T0.timestamp()) - 1),
    )  # fmt: skip
    record, rows = _record(user), FakeSessionRepository()
    await rows.create_session(record)  # step-up state persists on this row
    svc = StepUpService(repo, rows, enc, clock=clock)
    auth = _Auth(svc, _Sessions({"tok": record}))
    emitter = _Emitter()
    snap = PrincipalSnapshot(
        user_id=user,
        roles=frozenset({"owner" if owner_role else "viewer"}),
        permissions=frozenset({Permission.USERS_WRITE}),
    )
    app = FastAPI()
    app.include_router(
        make_step_up_router(
            auth,
            emitter,
            principal_resolver=_Resolver(snap),
            positions=positions or _Positions(),
        )
    )
    app.middleware("http")(make_read_only_guard(auth, emitter))

    @app.put("/users/{uid}/roles")
    async def roles(uid: str) -> dict[str, bool]:
        return {"ok": True}

    @app.post("/orders")
    async def orders() -> dict[str, bool]:
        return {"ok": True}

    return TestClient(app), emitter, seed, clock, user


_H = {"Authorization": "Bearer tok"}


def _code(seed: bytes, clock: _Clock) -> str:
    return generate_code(seed, time_step_for(clock.now.timestamp()))


async def test_reset_without_step_up_is_403_and_audited() -> None:
    c, em, *_ = await _build()
    r = c.post(f"/users/{uuid.uuid4()}/mfa/reset", headers=_H)
    assert r.status_code == 403 and r.json()["code"] == "step_up_required"
    assert "auth.step_up_required" in em.actions()


async def test_step_up_then_owner_reset_reveals_nothing_and_audits() -> None:
    c, em, seed, clock, _ = await _build()
    ok = c.post(
        "/auth/step-up", headers=_H, json={"code": _code(seed, clock), "action_class": "users"}
    )
    assert ok.status_code == 200 and ok.json()["single_use"] is False
    target = uuid.uuid4()
    prev = c.get(f"/users/{target}/mfa/reset-preview", headers=_H)
    assert prev.json()["open_position_count"] == 2
    r = c.post(f"/users/{target}/mfa/reset", headers=_H)
    assert r.status_code == 200
    assert set(r.json()) == {"target_user_id", "methods_revoked", "sessions_revoked"}
    assert "auth.step_up_granted" in em.actions() and "auth.mfa_reset_by_owner" in em.actions()
    reset = next(c for c in em.calls if c["action"] == "auth.mfa_reset_by_owner")
    assert reset["severity"] == Severity.CRITICAL


async def test_non_owner_cannot_reset() -> None:
    c, *_ = await _build(owner_role=False)
    assert c.post(f"/users/{uuid.uuid4()}/mfa/reset", headers=_H).status_code == 403


async def test_three_failures_make_session_read_only_on_write_routes() -> None:
    c, em, _seed, clock, _ = await _build()
    body = {"code": "000000", "action_class": "keys"}
    assert c.post("/auth/step-up", headers=_H, json=body).status_code == 401
    assert c.post("/auth/step-up", headers=_H, json=body).status_code == 401
    r = c.post("/auth/step-up", headers=_H, json=body)
    assert r.status_code == 403 and r.json()["code"] == "session_read_only"
    assert c.post("/orders", headers=_H).json()["code"] == "session_read_only"
    assert c.post("/orders").status_code == 200  # no token: guard defers to the route
    assert em.actions().count("auth.step_up_failed") == 3
    assert "auth.session_readonly_downgrade" in em.actions()
    for call in em.calls:
        if call["action"] in ("auth.step_up_failed", "auth.session_readonly_downgrade"):
            assert call["severity"] == Severity.ERROR
    clock.now += timedelta(minutes=5, seconds=1)
    assert c.post("/orders", headers=_H).status_code == 200


async def test_step_up_rejects_unauthenticated_and_bad_class() -> None:
    c, *_ = await _build()
    assert c.post("/auth/step-up", json={}).status_code == 401
    assert (
        c.post("/auth/step-up", headers=_H, json={"code": "1", "action_class": "x"}).status_code
        == 400
    )


async def test_dangerous_route_is_403_without_elevation_then_passes() -> None:
    c, em, seed, clock, _ = await _build()
    uid = uuid.uuid4()
    r = c.put(f"/users/{uid}/roles", headers=_H)
    assert r.status_code == 403 and r.json()["code"] == "step_up_required"
    assert "auth.step_up_required" in em.actions()
    c.post("/auth/step-up", headers=_H, json={"code": _code(seed, clock), "action_class": "users"})
    assert c.put(f"/users/{uid}/roles", headers=_H).status_code == 200
    clock.now += timedelta(minutes=5, seconds=1)
    assert c.put(f"/users/{uid}/roles", headers=_H).status_code == 403


async def test_preview_without_position_store_is_unavailable_and_reset_needs_ack() -> None:
    c, em, seed, clock, _ = await _build(positions=_NoStore())
    c.post("/auth/step-up", headers=_H, json={"code": _code(seed, clock), "action_class": "users"})
    target = uuid.uuid4()
    prev = c.get(f"/users/{target}/mfa/reset-preview", headers=_H).json()
    assert prev["open_position_count"] is None and prev["positions"] == "unavailable"
    assert prev["position_source"] == "not_deployed"
    assert prev["requires_acknowledge_unknown_positions"] is True
    r = c.post(f"/users/{target}/mfa/reset", headers=_H)
    assert r.status_code == 409 and r.json()["code"] == "positions_unknown"
    assert "auth.mfa_reset_by_owner" not in em.actions()
    ok = c.post(
        f"/users/{target}/mfa/reset", headers=_H, json={"acknowledge_unknown_positions": True}
    )
    assert ok.status_code == 200 and "auth.mfa_reset_by_owner" in em.actions()


async def test_preview_with_position_store_needs_no_ack() -> None:
    c, _em, seed, clock, _ = await _build()
    c.post("/auth/step-up", headers=_H, json={"code": _code(seed, clock), "action_class": "users"})
    prev = c.get(f"/users/{uuid.uuid4()}/mfa/reset-preview", headers=_H).json()
    assert prev["positions"] == "known" and prev["position_source"] == "oms"
    assert prev["requires_acknowledge_unknown_positions"] is False


#: Exactly what the merged M-020 modal (apps/web/src/routes/StepUpGate.tsx) posts.
def _modal_body(code: str) -> dict[str, str]:
    return {"code": code}


async def test_real_modal_payload_elevates_challenged_class_end_to_end() -> None:
    c, em, seed, clock, _ = await _build()
    uid = uuid.uuid4()
    denied = c.put(f"/users/{uid}/roles", headers=_H)
    assert denied.status_code == 403 and denied.json()["action_class"] == "users"
    ok = c.post("/auth/step-up", headers=_H, json=_modal_body(_code(seed, clock)))
    assert ok.status_code == 200 and ok.json()["action_class"] == "users"
    expires = datetime.fromisoformat(ok.json()["step_up_expires_at"])
    assert expires == clock.now + timedelta(minutes=5)
    assert c.put(f"/users/{uid}/roles", headers=_H).status_code == 200
    assert "auth.step_up_granted" in em.actions()


async def test_code_only_without_pending_challenge_is_400() -> None:
    c, _em, seed, clock, _ = await _build()
    r = c.post("/auth/step-up", headers=_H, json=_modal_body(_code(seed, clock)))
    assert r.status_code == 400


async def test_client_action_class_mismatching_challenge_is_400() -> None:
    c, _em, seed, clock, _ = await _build()
    c.put(f"/users/{uuid.uuid4()}/roles", headers=_H)
    r = c.post(
        "/auth/step-up", headers=_H, json={"code": _code(seed, clock), "action_class": "keys"}
    )
    assert r.status_code == 400
