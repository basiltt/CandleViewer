"""Contract-conformance tests (E03-T06 acceptance criterion: "Contract drift
between server and OpenAPI fails").

Runs against `docs/plan/22-api-openapi.yaml` and the live `create_app()`
route table so a route added to the FastAPI app without a matching OpenAPI
operation fails this suite before it ever reaches CI's `contract` job.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from candleviewer.api.contract_conformance import (
    ContractDriftError,
    assert_spec_is_valid,
    find_drift,
    load_openapi_spec,
    spec_paths,
)
from candleviewer.app import create_app
from candleviewer.settings import Settings


@pytest.fixture(scope="module")
def spec() -> dict:
    return load_openapi_spec()


def test_openapi_spec_is_structurally_valid(spec: dict) -> None:
    assert_spec_is_valid(spec)


def test_openapi_spec_has_paths(spec: dict) -> None:
    assert len(spec_paths(spec)) > 0


def _app_routes() -> list[tuple[str, str]]:
    app = create_app(Settings(git_sha="test", version="0.0.0-test"))
    routes: list[tuple[str, str]] = []
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if path is None or methods is None:
            continue
        for method in methods:
            if method == "HEAD":
                continue
            routes.append((path, method))
    return routes


def test_app_routes_have_no_contract_drift(spec: dict) -> None:
    """Scenario: contract drift between server and OpenAPI fails.

    Today's app only serves `/healthz`, `/readyz` and `/metrics` (R0
    scaffold) — none of which are declared REST-contract paths, so this
    exercises the allow-list path. Once a real route lands without a
    matching OpenAPI operation, this test fails with the CI-CON-001 message
    naming the exact route and method (the acceptance criterion's "job
    fails identifying the route and the offending field").
    """
    drift = find_drift(_app_routes(), spec)
    assert drift == [], "\n".join(str(d) for d in drift)


def test_contract_drift_error_names_route_and_method() -> None:
    """A synthetic drift case proves the failure message is actionable."""
    spec_with_no_paths: dict = {"paths": {}}
    drift = find_drift([("/orders", "post")], spec_with_no_paths)
    assert len(drift) == 1
    assert isinstance(drift[0], ContractDriftError)
    assert "/orders" in str(drift[0])
    assert "POST" in str(drift[0])


def test_openapi_spec_path_is_where_this_test_expects() -> None:
    from candleviewer.api.contract_conformance import OPENAPI_SPEC_PATH

    assert OPENAPI_SPEC_PATH.name == "22-api-openapi.yaml"
    assert Path(OPENAPI_SPEC_PATH).is_file()


_INVITE_OPS = [
    ("/users", "post"),
    ("/users/invites", "get"),
    ("/users/{userId}/invite", "post"),
    ("/users/{userId}/invite", "delete"),
    ("/invites/{inviteToken}", "get"),
    ("/invites/{inviteToken}", "post"),
    ("/invites/{inviteToken}/confirm", "post"),
]


@pytest.mark.parametrize(("path", "method"), _INVITE_OPS)
def test_invite_operations_declared_in_spec(spec: dict, path: str, method: str) -> None:
    """E09-S05: every invite route is declared in the OpenAPI contract."""
    assert method in spec["paths"][path]


def test_invite_redeem_bodies_forbid_extra_fields(spec: dict) -> None:
    """Role immutability is part of the contract: no free-form invitee body."""
    for path in ("/invites/{inviteToken}", "/invites/{inviteToken}/confirm"):
        schema = spec["paths"][path]["post"]["requestBody"]["content"]["application/json"]["schema"]
        assert schema["additionalProperties"] is False
        assert "role" not in schema["properties"]
