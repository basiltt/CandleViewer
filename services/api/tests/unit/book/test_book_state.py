"""BookState: apply/upsert/delete, validation, invariants, property test."""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.book.errors import BookInvariantError, BookPayloadError
from candleviewer.book.state import BookState
from candleviewer.exchange.base.models import BookLevel

from ._builders import lvl


def test_book_state_from_levels_orders_bids_desc_asks_asc() -> None:
    b = BookState.from_levels(200, [lvl(98, 1), lvl(99, 2)], [lvl(102, 1), lvl(101, 3)])
    bids, asks = b.top(5)
    assert [x.price_ticks for x in bids] == [99, 98]
    assert [x.price_ticks for x in asks] == [101, 102]


def test_book_state_apply_upsert_and_delete() -> None:
    b = BookState.from_levels(200, [lvl(99, 2)], [lvl(101, 3)])
    b.apply([lvl(99, 5), lvl(97, 1)], [lvl(101, 0)])
    bids, asks = b.as_dicts()
    assert bids == {97: Decimal(1), 99: Decimal(5)} and asks == {}


def test_book_state_delete_missing_level_is_noop() -> None:
    b = BookState.from_levels(200, [lvl(99, 2)], [])
    b.apply([lvl(50, 0)], [])
    assert b.as_dicts()[0] == {99: Decimal(2)}


def test_book_state_crossed_raises() -> None:
    b = BookState.from_levels(200, [lvl(99, 2)], [lvl(101, 3)])
    with pytest.raises(BookInvariantError) as ei:
        b.apply([lvl(101, 1)], [])
    assert ei.value.kind == "crossed"


@pytest.mark.parametrize("qty", ["-1", "NaN", "Infinity"])
def test_book_state_garbled_qty_rejected(qty: str) -> None:
    b = BookState(200)
    with pytest.raises(BookPayloadError):
        # model_construct bypasses pydantic's own finite check: defence in depth
        b.apply([BookLevel.model_construct(price=Decimal(1), qty=Decimal(qty), price_ticks=10)], [])


def test_book_state_snapshot_zero_size_rejected() -> None:
    with pytest.raises(BookPayloadError):
        BookState.from_levels(200, [lvl(99, 0)], [])


def test_book_state_oversized_payload_rejected() -> None:
    with pytest.raises(BookPayloadError):
        BookState.from_levels(1, [lvl(99, 1), lvl(98, 1)], [])


def test_book_state_unbounded_growth_rejected() -> None:
    b = BookState.from_levels(1, [lvl(99, 1)], [])
    b.apply([lvl(98, 1)], [])
    with pytest.raises(BookInvariantError):
        b.apply([lvl(97, 1)], [])


_ops = st.lists(
    st.tuples(st.integers(1, 40), st.integers(0, 5)), max_size=60
)  # (ticks, qty) bids only below 50


@settings(max_examples=200, deadline=None)
@given(_ops)
def test_book_state_equals_reference_dict(ops: list[tuple[int, int]]) -> None:
    b = BookState(200)
    ref: dict[int, Decimal] = {}
    for t, q in ops:
        b.apply([lvl(t, q)], [])
        if q == 0:
            ref.pop(t, None)
        else:
            ref[t] = Decimal(q)
    assert b.as_dicts()[0] == ref
    bids, _ = b.top(1000)
    assert [x.price_ticks for x in bids] == sorted(ref, reverse=True)
    assert all(x.qty > 0 for x in bids)
