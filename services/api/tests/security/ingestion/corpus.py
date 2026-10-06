"""E08-X02 adversarial corpus — kept apart from the legitimate E08-T05 fixtures.

Every payload here is *hostile by construction* and is built in code from a
recorded corpus frame (`tests/_corpus.py`) or from scratch, so it can never be
mistaken for an expected-behaviour baseline (ticket technical notes).

E08-Q03 hook: `iter_hostile_frames()` is the single entry point. When the
fault-injecting proxy lands, it replays exactly this iterator over its socket
instead of the in-process injection used today (deviation recorded in the PR).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from tests._corpus import frames

TS = 1_700_000_000_000
BOOK = frames("ws/orderbook_BTCUSDT.jsonl")
TRADES = frames("ws/clean_publicTrade_BTCUSDT.jsonl")
TICKERS = frames("ws/tickers_BTCUSDT.jsonl")


@dataclass(frozen=True)
class Hostile:
    case: str
    stream: str  # trade | ticker | book
    frame: str


def _dump(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"))


def trade(**rec: Any) -> str:
    base: dict[str, Any] = {"s": "BTCUSDT", "i": "t-1", "T": TS, "p": "100.0", "v": "1"}
    base.update({"S": "Buy"}, **rec)
    return _dump({"topic": "publicTrade.BTCUSDT", "ts": TS, "type": "snapshot", "data": [base]})


def ticker(**data: Any) -> str:
    return _dump({"topic": "tickers.BTCUSDT", "type": "snapshot", "ts": TS, "data": data})


def book(kind: str, u: int, bids: list[list[str]], asks: list[list[str]], **extra: Any) -> str:
    data: dict[str, Any] = {"s": "BTCUSDT", "b": bids, "a": asks, "u": u, "seq": u}
    msg: dict[str, Any] = {"topic": "orderbook.50.BTCUSDT", "type": kind, "ts": TS + u}
    msg.update(data=data, **extra)
    return _dump(msg)


def nested(depth: int) -> str:
    return '{"topic":"publicTrade.BTCUSDT","data":' + "[" * depth + "]" * depth + "}"


_NUMERIC = {
    "nan": "NaN",
    "inf": "Infinity",
    "neg_inf": "-Infinity",
    "neg": '"-1"',
    "neg_zero": '"-0"',
    "zero": '"0"',
    "word": '"abc"',
    "null": "null",
    "bool": "true",
    "list": "[1]",
}


def _malformed() -> Iterator[Hostile]:
    good = TRADES[0]
    yield Hostile("truncated_frame", "trade", good[: len(good) // 2])
    yield Hostile("invalid_utf8_surrogate", "trade", good[:-2] + "\udcff}]")
    yield Hostile("html_error_page", "trade", "<html><body>502 Bad Gateway</body></html>")
    yield Hostile("redirect_body", "trade", "Moved Permanently. Redirecting to /login")
    yield Hostile("top_level_array", "trade", "[1,2,3]")
    yield Hostile("extra_fields", "trade", trade(zz="x" * 64, nested={"a": [1]}))
    yield Hostile("string_for_ts", "trade", trade(T="soon"))
    for name, lit in _NUMERIC.items():
        frame = trade(p="__P__").replace('"__P__"', lit)
        yield Hostile(f"trade_price_{name}", "trade", frame)
        frame = trade(v="__V__").replace('"__V__"', lit)
        yield Hostile(f"trade_qty_{name}", "trade", frame)
    for field in ("s", "i", "T", "p", "v", "S"):
        yield Hostile(f"trade_null_{field}", "trade", trade(**{field: None}))
    yield Hostile("ticker_nan", "ticker", ticker(lastPrice="NaN"))
    yield Hostile("ticker_word", "ticker", ticker(markPrice="abc"))
    yield Hostile("ticker_bool", "ticker", ticker(lastPrice=True))
    yield Hostile("ticker_null_ts", "ticker", ticker().replace(f'"ts":{TS}', '"ts":null'))
    yield Hostile("book_nan_qty", "book", book("snapshot", 1, [["100.0", "NaN"]], []))
    yield Hostile("book_neg_price", "book", book("snapshot", 1, [["-100.0", "1"]], []))
    yield Hostile("book_null_u", "book", book("snapshot", 1, [], []).replace('"u":1', '"u":null'))
    yield Hostile("book_bad_row", "book", book("snapshot", 1, [["100.0"]], []))


def iter_hostile_frames() -> Iterator[Hostile]:
    """Every malformed frame that must be rejected with no domain event."""
    yield from _malformed()
