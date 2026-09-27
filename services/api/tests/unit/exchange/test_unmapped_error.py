"""Acceptance criterion 4: "Unmapped exchange error" — an adapter error not
in the taxonomy is re-raised as `UnknownStateError` with the original
preserved as `__cause__`, and a metric is incremented."""

from __future__ import annotations

from candleviewer.exchange.base.boundary import exchange_errors_total, translate_exchange_error
from candleviewer.exchange.base.errors import (
    AuthError,
    OmsErrorCode,
    UnknownStateError,
)


def _counter_value(label: str) -> float:
    for sample in exchange_errors_total.collect()[0].samples:
        if sample.name.endswith("_total") and sample.labels.get("class") == label:
            return sample.value
    return 0.0


def test_unmapped_error_is_wrapped_as_unknown_state_error_with_cause() -> None:
    original = ValueError("some library raised this and it is not in our taxonomy")
    wrapped = translate_exchange_error(original)
    assert isinstance(wrapped, UnknownStateError)
    assert wrapped.__cause__ is original


def test_unmapped_error_increments_unknown_state_metric() -> None:
    before = _counter_value(OmsErrorCode.UNKNOWN_STATE.value)
    translate_exchange_error(RuntimeError("boom"))
    after = _counter_value(OmsErrorCode.UNKNOWN_STATE.value)
    assert after == before + 1


def test_already_mapped_error_passes_through_unchanged() -> None:
    original = AuthError("bad signature")
    result = translate_exchange_error(original)
    assert result is original


def test_already_mapped_error_increments_its_own_class_metric() -> None:
    before = _counter_value(OmsErrorCode.AUTH_ERROR.value)
    translate_exchange_error(AuthError("bad signature"))
    after = _counter_value(OmsErrorCode.AUTH_ERROR.value)
    assert after == before + 1
