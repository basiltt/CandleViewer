"""Global deny-by-default wiring (QA #1648 d3)."""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.deny_by_default import (
    UndeclaredRouteAtBuildError,
    assert_app_routes_declared,
    declared_operations,
    make_deny_undeclared_dependency,
)
from candleviewer.app import create_app


def test_build_fails_for_route_without_declaration() -> None:
    app = FastAPI()

    @app.get("/widgets")
    async def widgets() -> dict[str, str]:
        return {}

    with pytest.raises(UndeclaredRouteAtBuildError, match="GET /widgets"):
        assert_app_routes_declared(app, load_openapi_spec())


def test_runtime_denies_undeclared_route_with_403() -> None:
    app = FastAPI(dependencies=[Depends(make_deny_undeclared_dependency(set()))])

    @app.get("/widgets")
    async def widgets() -> dict[str, str]:
        return {"ok": "yes"}

    assert TestClient(app).get("/widgets").status_code == 403


def test_real_app_builds_and_declared_routes_are_not_blanket_denied() -> None:
    app = create_app()
    declared = declared_operations(load_openapi_spec())
    assert ("PUT", "/users/{userId}/roles") in declared
    assert TestClient(app, client=("127.0.0.1", 50000)).get("/healthz").status_code == 200
