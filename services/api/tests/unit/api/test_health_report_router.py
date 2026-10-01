"""E04-T04: liveness/readiness/admin health endpoints (Gherkin scenarios)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api.health_report import make_health_report_router, migrations_at_head_check
from candleviewer.observability.health_metrics import bind_health_metrics
from candleviewer.observability.health_probes import (
    CallableProbe,
    ComponentState,
    HealthRegistry,
    ProbeResult,
)
from candleviewer.observability.metrics import CollectorRegistry, generate_latest
from candleviewer.settings import Settings


class _P:
    def __init__(self, perms: set[str]) -> None:
        self._perms = perms

    def has(self, permission: str) -> bool:
        return permission in self._perms


class _Resolver:
    def __init__(self, principal: _P | None) -> None:
        self._principal = principal

    def resolve(self, request: Request) -> _P | None:
        return self._principal


def _client(
    reg: HealthRegistry,
    resolver: _Resolver | None = None,
    checks: dict[str, Callable[[], Awaitable[bool]]] | None = None,
) -> TestClient:
    app = FastAPI()
    app.include_router(
        make_health_report_router(
            reg,
            version="1.2.3",
            git_sha="abc",
            environment="dev",
            ready_checks=checks,
            principal_resolver=resolver,
            ready_timeout_s=0.1,
        )
    )
    return TestClient(app)


def test_live_is_static_and_minimal() -> None:
    r = _client(HealthRegistry()).get("/health/live")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_ready_ok_and_503_names_only_components() -> None:
    async def ok() -> bool:
        return True

    async def bad() -> bool:
        raise RuntimeError("postgres://u:pw@h/db")

    c = _client(HealthRegistry(), checks={"postgres": ok})
    assert c.get("/health/ready").json() == {"status": "ready", "checks": {"postgres": "ok"}}
    c = _client(HealthRegistry(), checks={"postgres": bad, "questdb": ok})
    r = c.get("/health/ready")
    assert r.status_code == 503
    assert "postgres" in r.json()["detail"]
    assert "pw" not in r.text and "1.2.3" not in r.text
    assert r.headers["retry-after"] == "5"


async def test_migrations_check_blocks_on_behind_or_two_heads() -> None:
    async def one() -> list[str]:
        return ["h2"]

    async def two() -> list[str]:
        return ["h1", "h2"]

    async def at() -> str | None:
        return "h2"

    async def behind() -> str | None:
        return "h1"

    assert await migrations_at_head_check(one, at)() is True
    assert await migrations_at_head_check(one, behind)() is False
    assert await migrations_at_head_check(two, at)() is False


def test_ready_migration_state_named_when_blocking() -> None:
    async def behind() -> bool:
        return False

    r = _client(HealthRegistry(), checks={"migrations": behind}).get("/health/ready")
    assert r.status_code == 503
    assert "migrations" in r.json()["detail"]


async def _snapshotted() -> HealthRegistry:
    async def hang() -> ProbeResult:
        await asyncio.sleep(30)
        return ProbeResult(ComponentState.HEALTHY)

    async def ok() -> ProbeResult:
        return ProbeResult(ComponentState.HEALTHY, "pool 4/20")

    reg = HealthRegistry(probe_deadline_s=0.05)
    reg.register(CallableProbe("parquet_store", hang, timeout=10))
    reg.register(CallableProbe("postgres", ok))
    reg.register_placeholders()
    await reg.refresh()
    return reg


async def test_admin_health_report_shape_and_degraded() -> None:
    reg = await _snapshotted()
    c = _client(reg, _Resolver(_P({"admin:read"})))
    r = c.get("/admin/health")
    assert r.status_code == 200
    body = r.json()
    assert body["overall"] == "degraded"
    assert body["version"] == "1.2.3" and body["clock_offset_ms"] is None
    by = {x["name"]: x for x in body["components"]}
    assert by["parquet_store"]["detail"] == "probe timeout"
    assert by["postgres"]["last_good_at"] is not None
    assert by["postgres"]["latency_unit"] == "ms"
    assert by["oms"]["state"] == "not_deployed"
    assert len(body["components"]) == 10


async def test_admin_health_rbac() -> None:
    reg = await _snapshotted()
    assert _client(reg).get("/admin/health").status_code == 501
    assert _client(reg, _Resolver(None)).get("/admin/health").status_code == 401
    r = _client(reg, _Resolver(_P({"market:read"}))).get("/admin/health")
    assert r.status_code == 403
    assert "pool" not in r.text and "parquet" not in r.text


def test_admin_health_503_before_first_snapshot() -> None:
    r = _client(HealthRegistry(), _Resolver(_P({"admin:read"}))).get("/admin/health")
    assert r.status_code == 503


@pytest.mark.parametrize("path", ["/health/live", "/health/ready"])
def test_unauthenticated_probes_leak_no_build_info(path: str) -> None:
    r = _client(HealthRegistry()).get(path)
    assert "abc" not in r.text and "1.2.3" not in r.text


async def test_metrics_bound() -> None:
    reg = await _snapshotted()
    metrics = CollectorRegistry()
    bind_health_metrics(reg, metrics, Settings(git_sha="abc", version="1.2.3"))
    await reg.refresh()
    text = generate_latest(metrics).decode()
    assert 'build_info{commit="abc",env="demo",version="1.2.3"} 1.0' in text
    assert 'health_component_state{component="postgres"} 0.0' in text
    assert 'health_probe_duration_seconds_count{component="postgres"}' in text
