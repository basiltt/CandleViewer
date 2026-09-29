"""Tests for `tools/gen/export_instrument_policy_corpus.py` (ticket
`E08-S02`): determinism (CI-GEN-003 pattern) and internal consistency of
the generated corpus."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_MODULE_PATH = REPO_ROOT / "tools" / "gen" / "export_instrument_policy_corpus.py"

_spec = importlib.util.spec_from_file_location(
    "export_instrument_policy_corpus", _MODULE_PATH
)
assert _spec is not None and _spec.loader is not None
export_instrument_policy_corpus = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = export_instrument_policy_corpus
_spec.loader.exec_module(export_instrument_policy_corpus)


def test_build_document_is_deterministic_across_calls() -> None:
    first = export_instrument_policy_corpus.build_document()
    second = export_instrument_policy_corpus.build_document()
    assert first == second


def test_build_document_covers_every_violation_code() -> None:
    doc = export_instrument_policy_corpus.build_document()
    seen: set[str] = set()
    for case in doc["cases"]:
        seen.update(case["expected_violation_codes"])
    assert seen == set(doc["violation_codes"])


def test_rounded_price_is_always_a_tick_multiple() -> None:
    doc = export_instrument_policy_corpus.build_document()
    from decimal import Decimal

    for case in doc["cases"]:
        tick = Decimal(case["instrument"]["tick_size"])
        rounded = Decimal(case["expected_rounded_price"])
        assert (rounded % tick) == 0


def test_rounded_qty_never_exceeds_input_and_is_a_step_multiple() -> None:
    from decimal import Decimal

    doc = export_instrument_policy_corpus.build_document()
    for case in doc["cases"]:
        step = Decimal(case["instrument"]["qty_step"])
        qty = Decimal(case["qty"])
        rounded = Decimal(case["expected_rounded_qty"])
        assert rounded <= qty
        assert (rounded % step) == 0


def test_main_check_mode_prints_without_writing(
    tmp_path: Path, monkeypatch: object, capsys: object
) -> None:
    exit_code = export_instrument_policy_corpus.main(["--check"])
    assert exit_code == 0
