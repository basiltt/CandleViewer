"""Pagination helper tests (ticket deliverables "cursor pagination helper"
and "kline 1 000-row limit paging helper")."""

from __future__ import annotations

import pytest

from candleviewer.exchange.bybit.rest import paginate_cursor, paginate_klines


@pytest.mark.asyncio
async def test_paginate_cursor_stops_when_next_cursor_is_falsy() -> None:
    pages = {
        None: (["a", "b"], "cursor-2"),
        "cursor-2": (["c"], None),
    }

    async def fetch_page(cursor: str | None) -> tuple[list[str], str | None]:
        return pages[cursor]

    rows = await paginate_cursor(fetch_page)  # type: ignore[arg-type]
    assert rows == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_paginate_klines_walks_window_backwards_until_start_covered() -> None:
    # Two pages: page 1 covers [500, 1000], page 2 covers [0, 499].
    calls: list[tuple[int, int]] = []

    async def fetch_range(start_ms: int, end_ms: int) -> list[dict[str, object]]:
        calls.append((start_ms, end_ms))
        if end_ms >= 1000:
            return [{"start": 1000}, {"start": 500}]
        return [{"start": 0}]

    rows = await paginate_klines(fetch_range, start_ms=0, end_ms=1000, limit=2)
    assert {r["start"] for r in rows} == {1000, 500, 0}
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_paginate_klines_stops_on_empty_page() -> None:
    async def fetch_range(_start_ms: int, _end_ms: int) -> list[dict[str, object]]:
        return []

    rows = await paginate_klines(fetch_range, start_ms=0, end_ms=1000)
    assert rows == []
