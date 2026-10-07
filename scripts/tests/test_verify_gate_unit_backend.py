"""Regression guard for #1564: `pnpm verify` gate #3 must mirror CI's py lane."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE = (ROOT / "scripts" / "run-verify-gate.mjs").read_text(encoding="utf-8")
CI_PY = (ROOT / ".github" / "workflows" / "_job-py.yml").read_text(encoding="utf-8")


def _gate3_block() -> str:
    m = re.search(r'gate\(3, "unit-backend".*?\n\}\);', GATE, re.DOTALL)
    assert m, "gate #3 not found"
    return m.group(0)


def _ci_marker() -> str:
    m = re.search(r'uv run pytest -p no:cacheprovider -m "([^"]+)"', CI_PY)
    assert m, "CI py-lane marker expression not found"
    return m.group(1)


def test_gate3_runs_from_services_api() -> None:
    block = _gate3_block()
    assert 'cwd: path.join(REPO_ROOT, "services", "api")' in block


def test_gate3_marker_is_ci_expression_plus_not_integration() -> None:
    block = _gate3_block()
    m = re.search(r'"(not exchange_smoke[^"]+)"', block)
    assert m, "gate #3 marker expression not found"
    assert m.group(1) == f"{_ci_marker()} and not integration"


def test_gate3_still_runs_scripts_tests() -> None:
    block = _gate3_block()
    assert '"scripts/tests"' in block and '"scripts/gh/tests"' in block
