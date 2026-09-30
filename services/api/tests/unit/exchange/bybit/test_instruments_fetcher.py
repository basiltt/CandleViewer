"""`make_instruments_info_fetcher` (E08-S01-2): follows `nextPageCursor`,
always requests `category=linear`, bounds paging. Fake client, no network."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from candleviewer.exchange.bybit.instruments import (
    InstrumentParseError,
    make_instruments_info_fetcher,
)


class FakeClient:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self.pages = pages
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def get_public(
        self, path: str, *, params: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        self.calls.append((path, dict(params or {})))
        return self.pages[min(len(self.calls) - 1, len(self.pages) - 1)]


async def test_fetcher_follows_cursor_and_requests_linear() -> None:
    client = FakeClient(
        [
            {"result": {"list": [{"symbol": "BTCUSDT"}], "nextPageCursor": "c1"}},
            {"result": {"list": [{"symbol": "ETHUSDT"}], "nextPageCursor": ""}},
        ]
    )
    items = await make_instruments_info_fetcher(client)()
    assert [i["symbol"] for i in items] == ["BTCUSDT", "ETHUSDT"]
    assert client.calls[0] == (
        "/v5/market/instruments-info",
        {"category": "linear", "limit": 1000},
    )
    assert client.calls[1][1]["cursor"] == "c1"


async def test_fetcher_refuses_unbounded_paging() -> None:
    client = FakeClient([{"result": {"list": [], "nextPageCursor": "again"}}])
    with pytest.raises(InstrumentParseError):
        await make_instruments_info_fetcher(client)()
    assert len(client.calls) == 20


async def test_fetcher_rejects_non_list_result() -> None:
    client = FakeClient([{"result": {"list": "nope"}}])
    with pytest.raises(InstrumentParseError):
        await make_instruments_info_fetcher(client)()
