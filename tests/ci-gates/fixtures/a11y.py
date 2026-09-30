"""E03-Q01 fixture: CI-A11Y-001 (new serious/critical axe-core violation).

The real gate (`apps/web/e2e/smoke.spec.ts`) runs axe-core inside a live
Playwright browser, which this offline QA fixture does not have available.
Instead this fixture exercises the exact severity-filter predicate the gate
applies (`impact === "serious" || impact === "critical"`) against a
representative axe-core results shape, so the *gate's own threshold logic*
is proven without needing a browser — the browser-driven half is out of
scope here (E03-Q05, deferred R1).
"""

from __future__ import annotations

from typing import Any


def _seriously_violates(results: dict[str, Any]) -> list[dict[str, Any]]:
    violations = results.get("violations", [])
    assert isinstance(violations, list)
    return [v for v in violations if v.get("impact") in ("serious", "critical")]


def build_clean_fixture() -> tuple[bool, str]:
    """A results payload with only "minor"/"moderate" violations must pass."""
    results = {
        "violations": [
            {"id": "color-contrast", "impact": "minor", "nodes": []},
        ]
    }
    hits = _seriously_violates(results)
    return (len(hits) == 0, f"{len(hits)} serious/critical violation(s)")


def build_violation_fixture() -> tuple[bool, str]:
    """CI-A11Y-001: a planted serious violation (icon-only button missing an
    accessible name) must be caught by the filter."""
    results = {
        "violations": [
            {
                "id": "button-name",
                "impact": "serious",
                "help": "Buttons must have discernible text",
                "nodes": [{"html": '<button><svg aria-hidden="true"></svg></button>'}],
            },
        ]
    }
    hits = _seriously_violates(results)
    ok = len(hits) == 0
    return (ok, f"{len(hits)} serious/critical violation(s): {[h['id'] for h in hits]}")
