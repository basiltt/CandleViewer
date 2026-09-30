"""Contract tests for E09-T03's RBAC conformance surface: route-inventory
completeness and vocabulary single-source-of-truth.

Scenarios covered (ticket Gherkin):
- "Every route declares a permission or is explicitly public"
- "Vocabulary has one source of truth"
"""

from __future__ import annotations

import pytest

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.rbac_conformance import (
    UndeclaredRouteError,
    VocabularyMismatchError,
    assert_vocabulary_single_source,
    enum_permission_codes,
    find_undeclared_routes,
    seed_permission_codes,
    spec_permission_codes,
)


@pytest.fixture(scope="module")
def spec() -> dict:
    return load_openapi_spec()


def test_every_operation_declares_rbac_or_is_public(spec: dict) -> None:
    """Scenario: every route in the current spec passes today."""
    undeclared = find_undeclared_routes(spec)
    assert undeclared == [], "\n".join(str(u) for u in undeclared)


def test_undeclared_operation_fails() -> None:
    """Scenario: a newly added route whose declaration is missing fails."""
    synthetic_spec = {
        "paths": {
            "/widgets": {
                "get": {"operationId": "listWidgets"},
            }
        }
    }
    undeclared = find_undeclared_routes(synthetic_spec)
    assert len(undeclared) == 1
    assert isinstance(undeclared[0], UndeclaredRouteError)
    assert undeclared[0].path == "/widgets"
    assert undeclared[0].method == "get"


def test_public_marker_satisfies_declaration() -> None:
    """`security: []` alone (no `x-rbac`) still counts as declared."""
    synthetic_spec = {
        "paths": {
            "/healthz": {
                "get": {"operationId": "health", "security": []},
            }
        }
    }
    assert find_undeclared_routes(synthetic_spec) == []


def test_empty_permissions_with_scope_none_satisfies_declaration() -> None:
    """`x-rbac: {permissions: [], scope: none}` (e.g. `/auth/login`) is an
    explicit statement of "no permission needed", not a missing one."""
    synthetic_spec = {
        "paths": {
            "/auth/login": {
                "post": {
                    "operationId": "authLogin",
                    "security": [],
                    "x-rbac": {"permissions": [], "scope": "none"},
                },
            }
        }
    }
    assert find_undeclared_routes(synthetic_spec) == []


def test_rbac_vocabulary_single_source(spec: dict) -> None:
    """Scenario: vocabulary has one source of truth."""
    assert_vocabulary_single_source(spec)


def test_rbac_vocabulary_sets_are_identical(spec: dict) -> None:
    spec_codes = spec_permission_codes(spec)
    assert spec_codes == enum_permission_codes()
    assert spec_codes == seed_permission_codes()
    assert len(spec_codes) == 36


def test_vocabulary_mismatch_names_the_diverging_codes() -> None:
    synthetic_spec = {
        "paths": {
            "/x": {
                "get": {"x-rbac": {"permissions": ["made_up:code"], "scope": "none"}},
            }
        }
    }
    with pytest.raises(VocabularyMismatchError) as exc_info:
        assert_vocabulary_single_source(synthetic_spec)
    assert "made_up:code" in str(exc_info.value)
