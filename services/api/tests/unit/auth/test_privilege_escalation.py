"""Privilege-escalation suite + decision latency benchmark (QA #1648 d3).

Every permission the seed withholds from manager/viewer must be denied to
them and audited via `enforce`; decision p99 must stay < 200 microseconds.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any

import pytest

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import (
    Allow,
    ForbiddenError,
    PrincipalSnapshot,
    decide,
    enforce,
)

SEED = json.loads(
    (Path(__file__).parents[3] / "candleviewer" / "auth" / "rbac_seed.json").read_text("utf-8")
)


def _principal(role: str) -> PrincipalSnapshot:
    granted = SEED["role_permissions"][role]
    perms = frozenset(Permission) if granted == ["*"] else frozenset(Permission(c) for c in granted)
    return PrincipalSnapshot(uuid.uuid4(), frozenset({role}), perms)


class _Em:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def emit(self, action: str, **kw: Any) -> None:
        self.calls.append({"action": action, **kw})


_CASES = [
    (role, perm)
    for role in ("manager", "viewer")
    for perm in Permission
    if perm.value not in SEED["role_permissions"][role]
]


@pytest.mark.parametrize(("role", "perm"), _CASES)
def test_non_owner_denied_every_permission_outside_its_role(role: str, perm: Permission) -> None:
    principal, em = _principal(role), _Em()
    with pytest.raises(ForbiddenError):
        asyncio.run(enforce(principal, perm, emitter=em))
    assert [c["action"] for c in em.calls] == ["rbac.denied"]
    assert perm.value in em.calls[0]["reason"]


def test_owner_allowed_everything() -> None:
    owner = _principal("owner")
    assert all(isinstance(decide(owner, p), Allow) for p in Permission)


def test_decision_latency_p99_under_200us() -> None:
    principal = _principal("manager")
    samples: list[float] = []
    for _ in range(5000):
        t0 = time.perf_counter()
        decide(principal, Permission.ORDERS_WRITE)
        samples.append(time.perf_counter() - t0)
    samples.sort()
    assert samples[int(len(samples) * 0.99)] < 200e-6
