"""SR-041 / SR-152 double-submit CSRF token (E09-X02 F-1, #2090).

The guard is mounted on a minimal app (the session router + the middleware), not
on `app.py`; composition-root wiring is a separate change.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from candleviewer.api import csrf as api_csrf
from candleviewer.api.csrf import CSRF_PROBLEM_TYPE, make_csrf_guard
from candleviewer.api.sessions import REFRESH_COOKIE
from candleviewer.auth import csrf as auth_csrf
from candleviewer.auth.csrf import CSRF_COOKIE, CSRF_HEADER, CsrfTokens, tokens_match
from tests.unit.api.test_sessions_router import _Env, _h

_ORIGIN = "https://app.example"
_KEY = b"k" * 32


class _GuardEnv(_Env):
    def __init__(self, **kw: Any) -> None:
        self.tokens = CsrfTokens(_KEY)
        super().__init__(origins=frozenset({_ORIGIN}), csrf=self.tokens, **kw)
        self.app.middleware("http")(
            make_csrf_guard(self.tokens, self.audit.writer, sessions=self.svc)
        )

    async def login(self) -> tuple[Any, str]:
        m = await self.mint(uuid.uuid4())
        tok = self.tokens.issue(str(m.session_id))
        self.client.cookies.set(CSRF_COOKIE, tok)
        return m, tok


def _refusals(env: _Env) -> list[dict[str, Any]]:
    return [e for e in env.audit.writer.events if e["action"] == "auth.csrf_refused"]


@pytest.fixture()
def genv() -> _GuardEnv:
    return _GuardEnv()


async def test_csrf_absent_token_is_403_and_audited(genv: _GuardEnv) -> None:
    m = await genv.mint(uuid.uuid4())
    r = genv.client.post("/api/v1/auth/logout", headers=_h(m.access_token))
    assert r.status_code == 403
    assert r.json()["type"] == CSRF_PROBLEM_TYPE
    assert _refusals(genv)[-1]["reason"] == "csrf_token_missing"
    rec = await genv.repo.find_by_id(str(m.session_id))
    assert rec is not None and not rec.is_revoked  # refused before the route ran


async def test_csrf_cookie_without_header_is_403(genv: _GuardEnv) -> None:
    m, _ = await genv.login()
    r = genv.client.post("/api/v1/auth/logout", headers=_h(m.access_token))
    assert r.status_code == 403


async def test_csrf_mismatched_token_is_403_and_audited(genv: _GuardEnv) -> None:
    m, tok = await genv.login()
    hdr = {**_h(m.access_token), CSRF_HEADER: tok[:-1] + ("A" if tok[-1] != "A" else "B")}
    r = genv.client.post("/api/v1/auth/logout", headers=hdr)
    assert r.status_code == 403
    assert _refusals(genv)[-1]["reason"] == "csrf_token_mismatch"


async def test_csrf_token_from_other_session_is_403(genv: _GuardEnv) -> None:
    m = await genv.mint(uuid.uuid4())
    other = genv.tokens.issue(str(uuid.uuid4()))
    genv.client.cookies.set(CSRF_COOKIE, other)
    r = genv.client.post("/api/v1/auth/logout", headers={**_h(m.access_token), CSRF_HEADER: other})
    assert r.status_code == 403
    assert _refusals(genv)[-1]["reason"] == "csrf_token_unbound"


async def test_csrf_matching_token_passes(genv: _GuardEnv) -> None:
    m, tok = await genv.login()
    r = genv.client.post("/api/v1/auth/logout", headers={**_h(m.access_token), CSRF_HEADER: tok})
    assert r.status_code == 204
    assert not _refusals(genv)
    assert CSRF_COOKIE in r.headers.get("set-cookie", "")  # cleared on logout


async def test_csrf_safe_methods_not_checked(genv: _GuardEnv) -> None:
    m = await genv.mint(uuid.uuid4())
    assert genv.client.get("/api/v1/auth/session", headers=_h(m.access_token)).status_code != 403


async def test_csrf_token_rotates_on_refresh(genv: _GuardEnv) -> None:
    m, tok = await genv.login()
    r = genv.client.post(
        "/api/v1/auth/refresh",
        cookies={REFRESH_COOKIE: m.refresh_token},
        headers={"Origin": _ORIGIN, CSRF_HEADER: tok},
    )
    assert r.status_code == 200
    new = r.cookies.get(CSRF_COOKIE)
    assert new and new != tok
    set_cookie = next(h for h in r.headers.get_list("set-cookie") if h.startswith(CSRF_COOKIE))
    low = set_cookie.lower()
    assert "secure" in low and "samesite=strict" in low and "httponly" not in low
    new_access = r.json()["tokens"]["access_token"]
    # old token no longer fits the rotated session
    genv.client.cookies.set(CSRF_COOKIE, tok)
    old = genv.client.post("/api/v1/auth/logout", headers={**_h(new_access), CSRF_HEADER: tok})
    assert old.status_code == 403
    genv.client.cookies.set(CSRF_COOKIE, new)
    ok = genv.client.post("/api/v1/auth/logout", headers={**_h(new_access), CSRF_HEADER: new})
    assert ok.status_code == 204


async def test_cross_origin_refresh_still_refused_with_valid_csrf(genv: _GuardEnv) -> None:
    m, tok = await genv.login()
    for headers in ({}, {"Origin": "https://evil.example"}, {"Origin": "null"}):
        r = genv.client.post(
            "/api/v1/auth/refresh",
            cookies={REFRESH_COOKIE: m.refresh_token},
            headers={**headers, CSRF_HEADER: tok},
        )
        assert r.status_code == 403, headers
    rec = await genv.repo.find_by_id(str(m.session_id))
    assert rec is not None and not rec.is_revoked


def test_csrf_tokens_unit() -> None:
    t = CsrfTokens(_KEY)
    sid = str(uuid.uuid4())
    a, b = t.issue(sid), t.issue(sid)
    assert a != b and t.bound_to(a, sid) and not t.bound_to(a, str(uuid.uuid4()))
    assert not t.bound_to("garbage", sid) and not t.bound_to(".x", sid)
    assert not CsrfTokens(b"z" * 32).bound_to(a, sid)
    assert tokens_match(a, a) and not tokens_match(a, b)
    assert not tokens_match(None, a) and not tokens_match(a, "") and not tokens_match("", "")
    with pytest.raises(ValueError):
        CsrfTokens(b"short")


async def test_mutation_disabling_compare_is_caught(
    genv: _GuardEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutation check: with the compare stubbed to always-true, the mismatch
    case must stop being refused, proving the tests above depend on it."""
    monkeypatch.setattr(api_csrf, "tokens_match", lambda c, h: True)
    monkeypatch.setattr(auth_csrf.CsrfTokens, "bound_to", lambda self, t, s: True)
    m, tok = await genv.login()
    r = genv.client.post(
        "/api/v1/auth/logout", headers={**_h(m.access_token), CSRF_HEADER: tok + "x"}
    )
    assert r.status_code != 403  # mutant survives only if the compare is gone
