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

import json
from decimal import Decimal
from pathlib import Path

from candleviewer.domain.events import Instrument
from candleviewer.exchange.policy import FilterViolationCode, InstrumentPolicy

_CORPUS_PATH = (
    Path(__file__).resolve().parents[5]
    / "packages"
    / "fixtures"
    / "golden"
    / "policy"
    / "corpus.json"
)


def _load_corpus() -> dict[str, object]:
    return json.loads(_CORPUS_PATH.read_text(encoding="utf-8"))


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
    declared = set(corpus["violation_codes"])  # type: ignore[arg-type]
    assert declared == {code.value for code in FilterViolationCode}


def test_instrument_policy_agrees_with_every_generated_case() -> None:
    corpus = _load_corpus()
    for case in corpus["cases"]:  # type: ignore[union-attr]
        instrument = _instrument_from_case(case["instrument"])
        policy = InstrumentPolicy(instrument)
        price = Decimal(case["price"])
        qty = Decimal(case["qty"])

        assert policy.round_price(price) == Decimal(case["expected_rounded_price"]), case
        assert policy.round_qty(qty) == Decimal(case["expected_rounded_qty"]), case

        actual_codes = [v.code.value for v in policy.validate(price, qty)]
        assert actual_codes == case["expected_violation_codes"], case
