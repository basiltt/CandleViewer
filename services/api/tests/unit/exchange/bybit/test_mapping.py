"""Mapping-table tests (ticket scenario "Unknown retCode is loud" + DoD
"coverage >=85%"). Exhaustiveness over the documented §8.6 table and the
UnknownStateError fallback for anything not in it.
"""

from __future__ import annotations

import pytest

from candleviewer.exchange.base.errors import (
    AuthError,
    ClockDriftError,
    DuplicateClientIdError,
    InstrumentFilterError,
    InsufficientMarginError,
    NotFoundError,
    RateLimitError,
    UnknownStateError,
)
from candleviewer.exchange.bybit.mapping import map_ret_code


@pytest.mark.parametrize(
    ("ret_code", "expected_type"),
    [
        (10002, ClockDriftError),
        (10003, AuthError),
        (10004, AuthError),
        (10005, AuthError),
        (10006, RateLimitError),
        (10010, AuthError),
        (10016, RateLimitError),
        (10018, RateLimitError),
        (10019, RateLimitError),
        (10403, RateLimitError),
        (10404, InstrumentFilterError),
        (10429, RateLimitError),
        (20006, DuplicateClientIdError),
        (110001, NotFoundError),
        (110003, InstrumentFilterError),
        (110004, InsufficientMarginError),
        (110007, InsufficientMarginError),
        (110012, InsufficientMarginError),
        (110014, InsufficientMarginError),
        (110017, InstrumentFilterError),
        (110020, InstrumentFilterError),
        (110025, InstrumentFilterError),
        (110043, InstrumentFilterError),
        (110044, InstrumentFilterError),
        (110072, DuplicateClientIdError),
        (110079, UnknownStateError),
    ],
)
def test_map_ret_code_covers_documented_table(ret_code: int, expected_type: type) -> None:
    error = map_ret_code(ret_code, "some message")
    assert isinstance(error, expected_type)
    assert error.exchange_ret_code == ret_code


def test_map_ret_code_10001_generic_parameter_error() -> None:
    error = map_ret_code(10001, "params error: qty invalid")
    assert isinstance(error, InstrumentFilterError)
    assert not isinstance(error, DuplicateClientIdError)


def test_map_ret_code_10001_duplicate_order_link_id() -> None:
    error = map_ret_code(10001, "orderLinkId is duplicate")
    assert isinstance(error, DuplicateClientIdError)


@pytest.mark.parametrize("ret_code", [170001, 999999, -1, 42])
def test_map_ret_code_unknown_raises_unknown_state_error(ret_code: int) -> None:
    error = map_ret_code(ret_code, "never seen before")
    assert isinstance(error, UnknownStateError)
    assert error.exchange_ret_code == ret_code
    assert error.retryable is True
