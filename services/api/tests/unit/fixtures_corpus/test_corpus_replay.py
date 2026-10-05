"""E08-T05: shared corpus manifest, replay harness determinism/pacing, coverage of scenarios."""

from __future__ import annotations

import itertools
import json
from decimal import Decimal
from typing import Any

import pytest

from candleviewer.exchange.base.models import BookDelta, BookSnapshot
from candleviewer.exchange.base.ticker_delta import TickerDelta
from candleviewer.exchange.base.trade_print import TradePrint
from candleviewer.exchange.bybit.instruments import parse_instruments
from candleviewer.exchange.bybit.rest import paginate_klines
from tests._corpus import (
    FakeClock,
    corpus_path,
    encode,
    event_stream_bytes,
    frames,
    http_status,
    iter_corpus_files,
    manifest,
    replay,
    rest,
)

_REQUIRED = {"path", "symbol", "stream", "host", "capture_date", "notable_event", "size_cap_bytes"}


def test_manifest_documents_every_fixture_and_enforces_size_caps() -> None:
    entries = manifest()["fixtures"]
    on_disk = {
        p.relative_to(corpus_path("")).as_posix()
        for p in corpus_path("").rglob("*")
        if p.is_file() and p.name not in {"manifest.json", "schema_expectations.json"}
        and p.suffix in {".json", ".jsonl"}
    }  # fmt: skip
    assert on_disk == {e["path"] for e in entries}
    for entry in entries:
        assert _REQUIRED <= set(entry), entry["path"]
        assert corpus_path(entry["path"]).stat().st_size <= entry["size_cap_bytes"], entry["path"]
    assert sum(p.stat().st_size for p in iter_corpus_files()) < 2_500_000


def test_corpus_covers_every_required_scenario() -> None:
    events = " | ".join(e["notable_event"] for e in manifest()["fixtures"])
    symbols = {e["symbol"] for e in manifest()["fixtures"] if "clean" in e["notable_event"]}
    assert {"BTCUSDT", "ETHUSDT", "SOLUSDT"} <= symbols
    for needle in ("sequence gap", "reconnect", "delta-only burst", "page boundary", "delisted"):
        assert needle in events, needle
    assert rest("rest/error_10018.json")["retCode"] == 10018
    assert rest("rest/error_10002.json")["retCode"] == 10002
    assert http_status("rest/error_503.json") == 503
    with pytest.raises(KeyError):
        http_status("rest/nope.json")


async def test_replay_same_fixture_twice_is_byte_identical() -> None:
    raw = frames("ws/clean_publicTrade_ETHUSDT.jsonl") + frames("ws/gap_orderbook_ETHUSDT.jsonl")
    raw += frames("ws/burst_tickers_BTCUSDT.jsonl")
    first, second = await replay(raw), await replay(raw)
    assert len(first) > 1000
    assert event_stream_bytes(first) == event_stream_bytes(second)
    assert {type(e) for e in first} == {TradePrint, BookSnapshot, BookDelta, TickerDelta}


async def test_replay_paces_on_fake_clock_by_speed() -> None:
    raw = frames("ws/reconnect_publicTrade_ETHUSDT.jsonl")
    seen: list[str] = []

    async def sink(frame: str) -> None:
        seen.append(frame)

    real, fast = FakeClock(), FakeClock()
    await replay(raw, sink=sink, speed=1.0, sleep=real.sleep)
    await replay(raw, speed=10.0, sleep=fast.sleep)
    assert seen == raw
    assert real.now_s == pytest.approx(10 * fast.now_s)
    assert max(real.sleeps) == pytest.approx(16.0)  # the reconnect silence (15 s + 1 s cadence)


async def test_replay_rejects_bad_speed_and_unpaced_clock() -> None:
    with pytest.raises(ValueError, match="speed"):
        await replay([], speed=-1)
    with pytest.raises(ValueError, match="sleep"):
        await replay([], speed=1.0)
    assert await replay(["not json", '{"op":"pong"}']) == []
    with pytest.raises(TypeError):
        encode(object())


async def test_gap_window_parses_with_a_sequence_hole() -> None:
    events = await replay(frames("ws/gap_orderbook_ETHUSDT.jsonl"))
    ids = [e.update_id for e in events if isinstance(e, BookSnapshot | BookDelta)]
    holes = [b for a, b in itertools.pairwise(ids) if b != a + 1]
    assert len(holes) == 1


def _catalogue(rel: str) -> dict[str, Any]:
    result = parse_instruments(rest(rel)["result"]["list"], fetched_at_us=1)
    return {i.symbol: i for i in result.instruments}


def test_instruments_after_shows_delisting_and_tick_change() -> None:
    before = _catalogue("rest/instruments_before.json")
    after = _catalogue("rest/instruments_after.json")
    assert before["LUNAUSDT"].status == "trading" and after["LUNAUSDT"].status == "closed"
    assert before["SOLUSDT"].tick_size == Decimal("0.010")
    assert after["SOLUSDT"].tick_size == Decimal("0.005")


async def test_kline_page_boundary_set_drives_paginate_klines() -> None:
    pages = [rest(f"rest/kline_BTCUSDT_1_page{i}.json")["result"]["list"] for i in range(3)]
    calls: list[int] = []

    async def fetch(_start: int, end: int) -> list[dict[str, str]]:
        page = pages[len(calls)]
        calls.append(end)
        return [{"start": row[0]} for row in page]

    newest, oldest = int(pages[0][0][0]), int(pages[2][-1][0])
    rows = await paginate_klines(fetch, start_ms=oldest, end_ms=newest + 1, limit=200)
    assert len(calls) == 3 and len(rows) == 450
    assert calls[1] == int(pages[0][-1][0]) - 1  # next window ends just before the boundary
    assert json.dumps(pages[0][0]).startswith('["17')
