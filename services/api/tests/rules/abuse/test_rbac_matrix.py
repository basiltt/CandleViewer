"""E35-X02: every /rules* operation x role yields the documented outcome (R3 exit criterion 10)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.rules.test_rules_routes import _Env, _ir

RID = "00000000-0000-4000-8000-0000000000bb"
ROLES = {
    "anonymous": None,
    "no_perms": {"journal:read"},
    "reader": {"rules:read"},
    "writer": {"rules:read", "rules:write"},
}
# (method, path template, needs) ; needs = permission required
OPS = [
    ("GET", "/rules", "rules:read"),
    ("POST", "/rules", "rules:write"),
    ("GET", "/rules/{id}", "rules:read"),
    ("PUT", "/rules/{id}", "rules:write"),
    ("DELETE", "/rules/{id}", "rules:write"),
    ("GET", "/rules/{id}/versions", "rules:read"),
    ("PUT", "/rules/{id}/active-version", "rules:write"),
    ("PUT", "/rules/{id}/mode", "rules:write"),
]


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize(("method", "path", "needs"), OPS)
def test_route_by_role_matrix(role: str, method: str, path: str, needs: str) -> None:
    perms = ROLES[role]
    seed = _Env()
    rid = seed.create()
    e = _Env(perms if perms is not None else None, mgr=seed.mgr)
    e.anon = perms is None
    body: dict[str, Any] | None = {"ir": _ir()} if method in ("POST", "PUT") else None
    if path.endswith("active-version"):
        body = {"version_id": RID}
    if path.endswith("/mode"):
        body = {"mode": "simulate"}
    r = e.c.request(
        method,
        path.format(id=rid),
        json=body,
        headers={"If-Match": "1", "Idempotency-Key": "k"},
    )
    if perms is None:
        assert r.status_code == 401
    elif needs not in perms:
        assert r.status_code == 403
        assert seed.mgr._s._rows[rid].mode == "disabled"  # type: ignore[attr-defined]
    else:
        assert r.status_code not in (401, 403), r.text
