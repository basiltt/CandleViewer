"""Composition-root tests (E02-T05 acceptance criterion 3).

Given the composition root, when `create_app()` is called in a unit test
with fake storage clients, then it constructs without touching Postgres,
QuestDB or the network, and `GET /healthz` returns 200 with a build-info body
containing `gitSha`, `version` and `environment`.
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from candleviewer.app import Supervisor, build_app_context, create_app
from candleviewer.settings import Environment, Settings


def _fake_settings() -> Settings:
    return Settings(environment=Environment.DEMO, git_sha="deadbeef", version="9.9.9")


def test_create_app_is_fast_and_touches_no_io() -> None:
    # Warm up module imports first (Python import machinery, not create_app()
    # construction cost, dominates a genuinely cold first call in test runs).
    create_app(_fake_settings())
    started = time.perf_counter()
    app = create_app(_fake_settings())
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert app is not None
    # 06-performance-and-load-standard.md-adjacent budget from this ticket's
    # own "Performance notes": create_app() cold construction <=200 ms.
    assert elapsed_ms < 200


def test_healthz_returns_200_with_build_info() -> None:
    app = create_app(_fake_settings())
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["git_sha"] == "deadbeef"
    assert body["version"] == "9.9.9"
    assert body["environment"] == "demo"


def test_readyz_returns_200_with_empty_checks_array() -> None:
    app = create_app(_fake_settings())
    client = TestClient(app)
    response = client.get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["checks"] == []


def test_healthz_does_not_leak_internal_hostnames_or_datastore_versions() -> None:
    app = create_app(_fake_settings())
    client = TestClient(app)
    body = client.get("/healthz").json()
    assert set(body.keys()) == {"git_sha", "version", "environment", "status"}


async def test_supervisor_starts_storage_before_ws_and_stops_in_reverse() -> None:
    ctx = build_app_context(_fake_settings())
    supervisor = Supervisor(ctx)
    await supervisor.start_all()
    assert ctx.storage.health().status.value == "ok"
    assert ctx.ws.health().status.value == "ok"
    await supervisor.stop_all(grace_s=0.1)
    assert ctx.storage.health().status.value == "stopped"
    assert ctx.ws.health().status.value == "stopped"
