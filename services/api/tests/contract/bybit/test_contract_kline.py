"""E08-Q02 / E08-TC-F01: kline REST pages -> ascending series via `paginate_klines`.

Scope note: the adapter currently ships the paging helper only; there is no Bybit
list-of-lists -> `KlineEvent` mapper yet (`confirm -> confirmed`, `end = start + interval - 1`
are asserted by `E08-S06`'s unit suite against the port). The contract here pins what the
adapter boundary does own: wire ordering, page boundaries and series reconstruction.
"""

from __future__ import annotations

import itertools
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.exchange.bybit.rest import paginate_klines
from tests._corpus import rest

PAGE_FILES = (
    "rest/kline_BTCUSDT_1_page0.json",
    "rest/kline_BTCUSDT_1_page1.json",
    "rest/kline_BTCUSDT_1_page2.json",
)
PAGES = [rest(rel)["result"]["list"] for rel in PAGE_FILES]
ALL_DESC = [row for page in PAGES for row in page]  # wire order: newest first
STARTS_ASC = sorted(int(r[0]) for r in ALL_DESC)
STEP_MS = 60_000


def _as_wire(rows: list[list[str]]) -> list[dict[str, Any]]:
    return [{"start": r[0]} for r in rows]


def _server(limit: int) -> Any:
    """Independent oracle: a Bybit-shaped endpoint over the whole corpus (newest first, `limit`
    rows per call, window inclusive on both ends)."""
    calls: list[tuple[int, int]] = []

    async def fetch(start_ms: int, end_ms: int) -> list[dict[str, Any]]:
        calls.append((start_ms, end_ms))
        inside = [r for r in ALL_DESC if start_ms <= int(r[0]) <= end_ms]
        return _as_wire(inside[:limit])

    fetch.calls = calls  # type: ignore[attr-defined]
    return fetch


def test_corpus_pages_are_descending_contiguous_and_cross_page_boundaries_cleanly() -> None:
    starts = [int(r[0]) for r in ALL_DESC]
    assert starts == sorted(starts, reverse=True)
    assert len(starts) == len(set(starts)) == 450
    assert all(a - b == STEP_MS for a, b in itertools.pairwise(starts))
    assert [len(p) for p in PAGES] == [200, 200, 50]  # exact-limit pages + short tail


async def test_paging_across_the_boundary_has_no_duplicate_or_missing_open_time() -> None:
    fetch = _server(limit=200)
    rows = await paginate_klines(fetch, start_ms=STARTS_ASC[0], end_ms=STARTS_ASC[-1], limit=200)
    got = [int(r["start"]) for r in rows]
    assert len(got) == len(set(got)) == 450
    assert sorted(got) == STARTS_ASC


async def test_exact_multiple_of_limit_terminates_without_a_phantom_row() -> None:
    """Edge: 400 rows at limit 200 -> the second page is full AND the window is exhausted."""
    fetch = _server(limit=200)
    lo = STARTS_ASC[50]  # drop the 50 oldest -> exactly 400 rows remain
    rows = await paginate_klines(fetch, start_ms=lo, end_ms=STARTS_ASC[-1], limit=200)
    got = sorted(int(r["start"]) for r in rows)
    assert got == STARTS_ASC[50:] and len(got) == 400


@given(limit=st.integers(min_value=1, max_value=450), cut=st.integers(min_value=0, max_value=448))
@settings(max_examples=60, deadline=None)
async def test_arbitrary_split_points_reconstruct_the_single_call_series(
    limit: int, cut: int
) -> None:
    """Round-trip invariant: any page size / lower bound equals one unbounded call."""
    lo, hi = STARTS_ASC[cut], STARTS_ASC[-1]
    paged = await paginate_klines(_server(limit), start_ms=lo, end_ms=hi, limit=limit)
    single = await _server(10_000)(lo, hi)
    assert sorted(int(r["start"]) for r in paged) == sorted(int(r["start"]) for r in single)
    starts = [int(r["start"]) for r in paged]
    assert len(starts) == len(set(starts))


async def test_single_bar_window_returns_that_bar() -> None:
    only = STARTS_ASC[-1]
    rows = await paginate_klines(_server(200), start_ms=only, end_ms=only, limit=200)
    assert [int(r["start"]) for r in rows] == [only]


async def test_inverted_window_is_empty() -> None:
    rows = await paginate_klines(_server(200), start_ms=STARTS_ASC[5], end_ms=STARTS_ASC[4])
    assert rows == []


@given(
    lo=st.integers(min_value=0, max_value=449),
    span=st.integers(min_value=0, max_value=3),
    limit=st.integers(min_value=1, max_value=450),
)
@settings(max_examples=80, deadline=None)
async def test_inclusive_window_returns_exactly_the_bars_inside(
    lo: int, span: int, limit: int
) -> None:
    """One-bar (span 0), two-bar (span 1) and page-boundary-exact windows (limit == bars)."""
    hi_i = min(lo + span, 449)
    start, end = STARTS_ASC[lo], STARTS_ASC[hi_i]
    for lim in (limit, hi_i - lo + 1):
        rows = await paginate_klines(_server(lim), start_ms=start, end_ms=end, limit=lim)
        assert sorted(int(r["start"]) for r in rows) == STARTS_ASC[lo : hi_i + 1]


async def test_empty_page_stops_paging() -> None:
    async def fetch(_s: int, _e: int) -> list[dict[str, Any]]:
        return []

    assert await paginate_klines(fetch, start_ms=0, end_ms=10**12, limit=1000) == []
