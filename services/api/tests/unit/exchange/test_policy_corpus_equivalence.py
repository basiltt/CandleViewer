"""Cross-language equivalence proof (ticket `E08-S02`, "Client and server
never disagree" scenario): the generated corpus consumed by both
`services/api` and `packages/protocol` must match `InstrumentPolicy`
exactly for every case.

This test runs inside the backend's own test job (the full `candleviewer`
environment is available here, unlike the codegen script itself — see
`tools/gen/export_instrument_policy_corpus.py`'s module docstring for why
that script is stdlib-only). It is what keeps the generator from silently
drifting into "a second implementation" of the rounding/validation
algorithm — exactly the class of bug `US-MKT-004` exists to prevent.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from candleviewer.domain.events import Instrument
from candleviewer.exchange.policy import FilterViolationCode, InstrumentPolicy

_REPO_ROOT = Path(__file__).resolve().parents[5]
_POLICY_DIR = _REPO_ROOT / "packages" / "fixtures" / "golden" / "policy"
_CORPUS_PATH = _POLICY_DIR / "corpus.json"
_RULES_PATH = _POLICY_DIR / "rules.json"


def _load_generator(name: str) -> ModuleType:
    """Imports a stdlib-only `tools/gen/` exporter by path (they are not a
    package). Only `build_document()` is used — nothing is written."""
    spec = importlib.util.spec_from_file_location(name, _REPO_ROOT / "tools" / "gen" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _render(document: object) -> bytes:
    """The exact serialisation both exporters use (`indent=2`, insertion order,
    `ensure_ascii=False`, trailing LF, UTF-8)."""
    text = json.dumps(document, indent=2, sort_keys=False, ensure_ascii=False) + "\n"
    return text.encode("utf-8")


def _load_corpus() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(_CORPUS_PATH.read_text(encoding="utf-8"))
    return loaded


def _instrument_from_case(raw: dict[str, str]) -> Instrument:
    return Instrument.model_validate(
        {
            "symbol": raw["symbol"],
            "base_coin": "BTC",
            "quote_coin": "USDT",
            "settle_coin": "USDT",
            "status": raw["status"],
            "contract_type": "linear_perpetual",
            "launch_time": 0,
            "tick_size": Decimal(raw["tick_size"]),
            "price_scale": 1,
            "min_price": Decimal("0.01"),
            "max_price": Decimal("999999"),
            "qty_step": Decimal(raw["qty_step"]),
            "min_order_qty": Decimal(raw["min_order_qty"]),
            "max_order_qty": Decimal(raw["max_order_qty"]),
            "max_mkt_order_qty": Decimal(raw["max_order_qty"]),
            "min_notional": Decimal(raw["min_notional"]),
            "max_leverage": Decimal("100"),
            "min_leverage": Decimal("1"),
            "leverage_step": Decimal("0.01"),
            "funding_interval_min": 480,
            "upper_funding_rate": Decimal("0.00375"),
            "lower_funding_rate": Decimal("-0.00375"),
            "copy_trading": False,
            "metadata_version": 1,
            "fetched_at": 0,
        }
    )


def test_corpus_file_exists_and_is_non_empty() -> None:
    corpus = _load_corpus()
    cases = corpus["cases"]
    assert isinstance(cases, list)
    assert len(cases) > 0


def test_corpus_declares_every_filter_violation_code() -> None:
    corpus = _load_corpus()
    declared = set(corpus["violation_codes"])
    assert declared == {code.value for code in FilterViolationCode}


def test_instrument_policy_agrees_with_every_generated_case() -> None:
    corpus = _load_corpus()
    for case in corpus["cases"]:
        instrument = _instrument_from_case(case["instrument"])
        policy = InstrumentPolicy(instrument)
        price = Decimal(case["price"])
        qty = Decimal(case["qty"])

        assert policy.round_price(price) == Decimal(case["expected_rounded_price"]), case
        assert policy.round_qty(qty) == Decimal(case["expected_rounded_qty"]), case

        actual_codes = [v.code.value for v in policy.validate(price, qty)]
        assert actual_codes == case["expected_violation_codes"], case


@pytest.mark.parametrize(
    ("generator", "committed"),
    [
        ("export_instrument_policy_corpus", _CORPUS_PATH),
        ("export_instrument_policy_rules", _RULES_PATH),
    ],
)
def test_committed_policy_fixture_round_trips_byte_identical(
    generator: str, committed: Path
) -> None:
    """The committed golden file is byte-for-byte what its generator emits
    (same JSON style, one array element per line, LF endings), so running
    `pnpm generate` leaves a clean tree and no formatter may reflow it
    (C-13.7). Backend-side guard for the root `tests/gen` suite, which the
    backend CI job does not run."""
    module = _load_generator(generator)
    committed_bytes = committed.read_bytes()
    assert b"\r" not in committed_bytes, f"{committed.name} must be LF-only"
    assert committed_bytes == _render(module.build_document()), committed.name
