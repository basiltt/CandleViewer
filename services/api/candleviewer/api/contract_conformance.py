"""E03-T06: contract conformance checks for the `contract` CI job.

Two conformance surfaces per ADR-0013 rule 3 and the ticket scope:

1. `docs/plan/22-api-openapi.yaml` is a structurally valid OpenAPI 3.1
   document (schemathesis/consumer tests further down the pyramid assume
   this holds).
2. Every route the FastAPI app actually registers resolves to an operation
   declared in the spec — a route the server serves that the contract does
   not document is drift (CI-CON-001), caught here without needing the
   full app wired up yet (R0: only `/healthz`, `/readyz`, `/metrics` exist).

`/metrics` is Prometheus-format, not part of the REST contract (see
`docs/plan/22-api-openapi.yaml` inline note) and is excluded deliberately.

Stdlib + PyYAML + openapi-spec-validator only; no network.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml
from openapi_spec_validator import validate as validate_openapi_spec

REPO_ROOT = Path(__file__).resolve().parents[4]
OPENAPI_SPEC_PATH = REPO_ROOT / "docs" / "plan" / "22-api-openapi.yaml"

# Routes the app serves that are intentionally outside the REST contract
# (operational/observability endpoints, not product API surface).
NON_CONTRACT_ROUTES = frozenset(
    {"/metrics", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
)


class ContractDriftError(Exception):
    """Raised when a server route is absent from the OpenAPI contract."""

    def __init__(self, route: str, method: str) -> None:
        self.route = route
        self.method = method
        super().__init__(
            f"CI-CON-001: contract drift — {method.upper()} {route} is served by "
            f"the app but not declared in {OPENAPI_SPEC_PATH.relative_to(REPO_ROOT)}"
        )


def load_openapi_spec(spec_path: Path = OPENAPI_SPEC_PATH) -> dict[str, Any]:
    with spec_path.open(encoding="utf-8") as fh:
        return cast(dict[str, Any], yaml.safe_load(fh))


def assert_spec_is_valid(spec: dict[str, Any]) -> None:
    """Raises `openapi_spec_validator.exceptions.OpenAPIValidationError` on an
    invalid document; the caller decides how to surface that (CI job step
    failure output already includes the offending schema path)."""
    validate_openapi_spec(spec)


def spec_paths(spec: dict[str, Any]) -> set[str]:
    return set(spec.get("paths", {}).keys())


def _route_matches_spec(route: str, declared_paths: set[str]) -> bool:
    """FastAPI routes use `{param}` path params identically to OpenAPI, so an
    exact match after excluding non-contract routes is sufficient here; a
    templated-vs-literal mismatch would need a segment-aware matcher, which
    is unnecessary while every route is either declared verbatim or on the
    `NON_CONTRACT_ROUTES` allow-list."""
    return route in declared_paths


def find_drift(app_routes: list[tuple[str, str]], spec: dict[str, Any]) -> list[ContractDriftError]:
    """`app_routes` is a list of (path, http_method) tuples as served by the
    app (e.g. from `app.routes`). Returns one `ContractDriftError` per route
    not covered by the spec and not on the allow-list."""
    declared = spec_paths(spec)
    drift: list[ContractDriftError] = []
    for path, method in app_routes:
        if path in NON_CONTRACT_ROUTES:
            continue
        if not _route_matches_spec(path, declared):
            drift.append(ContractDriftError(path, method))
    return drift
