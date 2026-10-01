"""`/health/live`, `/health/ready`, `/admin/health` (E04-T04, ADR-0014 section 7).

Contract: `docs/plan/22-api-openapi.yaml` (server base `/api/v1`, mounted by the
app under that prefix). The two probes are unauthenticated and therefore
disclose only a coarse state word and component *names* - no versions, hosts,
details or stack traces. `/admin/health` is `admin:read` gated and is served
from the registry's cached snapshot; it never runs probes on the request path.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Any, Protocol

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from candleviewer.observability.health_probes import HealthRegistry, HealthSnapshot

ADMIN_READ = "admin:read"

#: A readiness check returns True when the dependency is ready. Exceptions
#: and timeouts count as not ready; they are never surfaced to the caller.
ReadyCheck = Callable[[], Awaitable[bool]]


class _Principal(Protocol):
    def has(self, permission: str) -> bool: ...


class _PrincipalResolver(Protocol):
    def resolve(self, request: Request) -> _Principal | None: ...


def _problem(status: int, title: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"type": "about:blank", "title": title, "status": status, "detail": detail},
        media_type="application/problem+json",
    )


def _iso(ts: datetime | None) -> str | None:
    return ts.isoformat().replace("+00:00", "Z") if ts is not None else None


def render_report(
    snap: HealthSnapshot,
    *,
    version: str,
    git_sha: str,
    environment: str,
    uptime_seconds: int,
    clock_offset_ms: int | None,
    alerts_active: int = 0,
) -> dict[str, Any]:
    """Wire shape of `HealthReport`; also the WS `system` `health` block."""
    return {
        "overall": snap.overall.value,
        "version": version,
        "git_sha": git_sha,
        "environment": environment,
        "uptime_seconds": uptime_seconds,
        "server_time": _iso(snap.taken_at),
        # None -> not_deployed until the exchange time sync (E08) lands; never a fake 0.
        "clock_offset_ms": clock_offset_ms,
        "components": [
            {
                "name": c.name,
                "state": c.state.value,
                "latency_ms": c.latency_ms,
                "latency_unit": "ms",
                "detail": c.detail,
                "last_good_at": _iso(c.last_good_at),
            }
            for c in snap.components
        ],
        "alerts_active": alerts_active,
    }


def make_health_report_router(
    registry: HealthRegistry,
    *,
    version: str,
    git_sha: str,
    environment: str,
    ready_checks: Mapping[str, ReadyCheck] | None = None,
    principal_resolver: _PrincipalResolver | None = None,
    ready_timeout_s: float = 2.0,
    clock_offset_ms: Callable[[], int | None] = lambda: None,
    started_monotonic: float | None = None,
) -> APIRouter:
    router = APIRouter(tags=["admin"])
    started = started_monotonic if started_monotonic is not None else time.monotonic()
    checks = dict(ready_checks or {})

    @router.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/health/ready")
    async def ready() -> JSONResponse:
        import asyncio

        async def run(fn: ReadyCheck) -> bool:
            try:
                return bool(await asyncio.wait_for(fn(), timeout=ready_timeout_s))
            except Exception:
                return False

        names = list(checks)
        results = await asyncio.gather(*(run(checks[n]) for n in names))
        outcome = {n: ("ok" if r else "fail") for n, r in zip(names, results, strict=True)}
        if all(results):
            return JSONResponse({"status": "ready", "checks": outcome})
        unready = ", ".join(n for n in names if outcome[n] == "fail")
        resp = _problem(503, "Service unavailable", f"not ready: {unready}")
        resp.headers["Retry-After"] = "5"
        return resp

    @router.get("/admin/health")
    def admin_health(request: Request) -> JSONResponse:
        if principal_resolver is None:
            return _problem(501, "Not implemented", "no principal resolver wired")
        principal = principal_resolver.resolve(request)
        if principal is None:
            return _problem(401, "Unauthorized", "no verified session for this request")
        if not principal.has(ADMIN_READ):
            return _problem(403, "Forbidden", f"missing permission: {ADMIN_READ}")
        snap = registry.snapshot()
        if snap is None:
            return _problem(503, "Service unavailable", "health snapshot not yet available")
        body = render_report(
            snap,
            version=version,
            git_sha=git_sha,
            environment=environment,
            uptime_seconds=int(time.monotonic() - started),
            clock_offset_ms=clock_offset_ms(),
        )
        return JSONResponse(body)

    return router


def migrations_at_head_check(
    heads: Callable[[], Awaitable[list[str]]],
    current: Callable[[], Awaitable[str | None]],
) -> ReadyCheck:
    """Ready only when the code has exactly one head and the DB is at it."""

    async def check() -> bool:
        code_heads = await heads()
        return len(code_heads) == 1 and await current() == code_heads[0]

    return check
