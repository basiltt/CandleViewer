"""Tests for `tools/gen/export_instrument_policy_rules.py` (ticket
`E08-S02`): determinism and agreement with the Python source of truth's own
enum members."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_MODULE_PATH = REPO_ROOT / "tools" / "gen" / "export_instrument_policy_rules.py"

_spec = importlib.util.spec_from_file_location(
    "export_instrument_policy_rules", _MODULE_PATH
)
assert _spec is not None and _spec.loader is not None
export_instrument_policy_rules = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = export_instrument_policy_rules
_spec.loader.exec_module(export_instrument_policy_rules)


def test_build_document_is_deterministic_across_calls() -> None:
    first = export_instrument_policy_rules.build_document()
    second = export_instrument_policy_rules.build_document()
    assert first == second


def test_main_check_mode_prints_without_writing() -> None:
    exit_code = export_instrument_policy_rules.main(["--check"])
    assert exit_code == 0


def test_violation_codes_match_policy_module_enum() -> None:
    sys.path.insert(0, str(REPO_ROOT / "services" / "api"))
    try:
        from candleviewer.exchange.policy import FilterViolationCode
    finally:
        sys.path.pop(0)

    doc = export_instrument_policy_rules.build_document()
    assert set(doc["violation_codes"]) == {code.value for code in FilterViolationCode}
