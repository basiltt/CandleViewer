"""`BookState` - the L2 book for one `(env, symbol, depth)` (E08-S05).

Hot path (catalogue §1.2 / INV-B14-a): plain code, never a statechart.
Levels are parallel arrays (ticks ascending, qty, price) kept sorted with
`bisect`, the shape measured by E08-K01 and portable to a native extension.
Bids are read from the end of their arrays (descending), asks from the start.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Sequence
from decimal import Decimal

from candleviewer.book.errors import BookInvariantError, BookPayloadError
from candleviewer.exchange.base.models import BookLevel


class _Side:
    __slots__ = ("price", "qty", "ticks")

    def __init__(self) -> None:
        self.ticks: list[int] = []
        self.qty: list[Decimal] = []
        self.price: list[Decimal] = []

    def upsert(self, lvl: BookLevel) -> None:
        i = bisect_left(self.ticks, lvl.price_ticks)
        if i < len(self.ticks) and self.ticks[i] == lvl.price_ticks:
            self.qty[i] = lvl.qty
            self.price[i] = lvl.price
        else:
            self.ticks.insert(i, lvl.price_ticks)
            self.qty.insert(i, lvl.qty)
            self.price.insert(i, lvl.price)

    def delete(self, ticks: int) -> None:
        i = bisect_left(self.ticks, ticks)
        if i < len(self.ticks) and self.ticks[i] == ticks:
            del self.ticks[i], self.qty[i], self.price[i]

    def __len__(self) -> int:
        return len(self.ticks)


def _validate(levels: Sequence[BookLevel], *, allow_zero: bool, bound: int) -> None:
    """Security note: reject garbled payloads before any mutation."""
    if len(levels) > bound:
        raise BookPayloadError(f"level count {len(levels)} exceeds tier bound {bound}")
    for lvl in levels:
        if not lvl.qty.is_finite() or not lvl.price.is_finite():
            raise BookPayloadError("non-finite price/qty")
        if lvl.qty < 0 or (lvl.qty == 0 and not allow_zero):
            raise BookPayloadError("negative or zero resting size")


class BookState:
    """Two sorted price->size sides with O(log n) lookup."""

    __slots__ = ("_asks", "_bids", "depth")

    def __init__(self, depth: int) -> None:
        self.depth = depth
        self._bids = _Side()
        self._asks = _Side()

    @classmethod
    def from_levels(
        cls, depth: int, bids: Sequence[BookLevel], asks: Sequence[BookLevel]
    ) -> BookState:
        _validate(bids, allow_zero=False, bound=depth)
        _validate(asks, allow_zero=False, bound=depth)
        book = cls(depth)
        for lvl in bids:
            book._bids.upsert(lvl)
        for lvl in asks:
            book._asks.upsert(lvl)
        book.check()
        return book

    def apply(self, bids: Sequence[BookLevel], asks: Sequence[BookLevel]) -> None:
        """Apply one delta (qty == 0 deletes). Validates first, then checks
        the book invariants; a violation raises and the caller resyncs."""
        bound = 2 * self.depth
        _validate(bids, allow_zero=True, bound=bound)
        _validate(asks, allow_zero=True, bound=bound)
        for side, levels in ((self._bids, bids), (self._asks, asks)):
            for lvl in levels:
                if lvl.qty == 0:
                    side.delete(lvl.price_ticks)
                else:
                    side.upsert(lvl)
        self.check()

    def check(self) -> None:
        """No crossed book; size bound per tier (sorting is structural)."""
        if self._bids.ticks and self._asks.ticks and self._bids.ticks[-1] >= self._asks.ticks[0]:
            raise BookInvariantError("crossed")
        if len(self._bids) > 2 * self.depth or len(self._asks) > 2 * self.depth:
            raise BookInvariantError("unbounded")

    def top(self, n: int) -> tuple[tuple[BookLevel, ...], tuple[BookLevel, ...]]:
        b, a = self._bids, self._asks
        nb, na = min(n, len(b)), min(n, len(a))
        bids = tuple(
            BookLevel(price=b.price[i], qty=b.qty[i], price_ticks=b.ticks[i])
            for i in range(len(b) - 1, len(b) - 1 - nb, -1)
        )
        asks = tuple(
            BookLevel(price=a.price[i], qty=a.qty[i], price_ticks=a.ticks[i]) for i in range(na)
        )
        return bids, asks

    def snapshot(self) -> tuple[tuple[BookLevel, ...], tuple[BookLevel, ...]]:
        return self.top(max(len(self._bids), len(self._asks)))

    def as_dicts(self) -> tuple[dict[int, Decimal], dict[int, Decimal]]:
        return dict(zip(self._bids.ticks, self._bids.qty, strict=True)), dict(
            zip(self._asks.ticks, self._asks.qty, strict=True)
        )
