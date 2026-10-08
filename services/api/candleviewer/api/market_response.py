"""Shared `KlineResponse` assembly for `/market/klines` and `/market/bars` (E12-T05, #398).

One place builds what both routes return, so the two cannot drift from `22-api-openapi.yaml`:
RFC 9457 problems carrying a catalogued `code`, the opaque bar cursor, `DataMeta`, the
null-not-zero delta rule and the response size ceiling (SR-E12-01).

**Cursor.** Opaque to clients (OpenAPI `MarketCursor`). Today it encodes the next page's start
`ts` (µs); after migration 0004 it encodes `(generation, index)` (TODO(#2017)). The `v1:`
version tag lets the server reject a cursor from another encoding with `invalid_cursor`.

**Null, not zero (BR-07).** Exchange klines carry no order flow, so a kline-sourced bar's
`delta`/`min_delta`/`max_delta`/`cvd` are `null` when `include_delta=true`; a zero would be a lie
that reaches CVD and rules. Tape-built bars carry their stored values; `cvd` is not persisted
per bar, so it is `null` there too.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Final, Protocol

import orjson
from fastapi.responses import JSONResponse, Response

from candleviewer.bars.limits import RESPONSE_MAX_BYTES

_PROBLEM_MEDIA: Final = "application/problem+json"
_ERR_BASE: Final = "https://candleviewer.local/errors/"
_CURSOR_TAG: Final = "v1:"
_CURSOR_MAX_LEN: Final = 128
_DELTA_FIELDS: Final = ("delta", "min_delta", "max_delta")


class InvalidCursor(ValueError):
    """The cursor is not one this server issued (400 `invalid_cursor`)."""


def problem(status: int, code: str, title: str, detail: str) -> JSONResponse:
    """RFC 9457 body matching `components.schemas.Problem` (`code` is required)."""
    return JSONResponse(
        status_code=status,
        content={
            "type": f"{_ERR_BASE}{code}",
            "title": title,
            "status": status,
            "code": code,
            "detail": detail,
        },
        media_type=_PROBLEM_MEDIA,
    )


def encode_cursor(ts_us: int) -> str:
    raw = f"{_CURSOR_TAG}{ts_us}".encode("ascii")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> int:
    if not cursor or len(cursor) > _CURSOR_MAX_LEN or not cursor.isascii():
        raise InvalidCursor("cursor is empty or too long")
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode("ascii")
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise InvalidCursor("cursor is not valid base64") from exc
    body = raw.removeprefix(_CURSOR_TAG)
    if body == raw or not body.isdigit() or len(body) > 19:
        raise InvalidCursor("cursor has an unknown encoding")
    return int(body)


def iso_us(ts_us: int) -> str:
    return datetime.fromtimestamp(ts_us / 1_000_000, tz=UTC).isoformat()


class BarRowLike(Protocol):
    """What either tier hands the assembler. Kline rows lack the order-flow attributes."""

    @property
    def ts_us(self) -> int: ...
    @property
    def open(self) -> str: ...
    @property
    def high(self) -> str: ...
    @property
    def low(self) -> str: ...
    @property
    def close(self) -> str: ...
    @property
    def volume(self) -> str: ...
    @property
    def turnover(self) -> str: ...
    @property
    def confirmed(self) -> bool: ...


def serialize_bar(row: BarRowLike, *, include_delta: bool) -> dict[str, object]:
    bar: dict[str, object] = {
        "t": iso_us(row.ts_us),
        "o": row.open,
        "h": row.high,
        "l": row.low,
        "c": row.close,
        "v": row.volume,
        "turnover": row.turnover,
        "confirm": row.confirmed,
    }
    close_ts = getattr(row, "close_ts_us", None)
    if isinstance(close_ts, int):
        bar["close_time"] = iso_us(close_ts)
    if include_delta:
        trades = getattr(row, "trades", None)
        if isinstance(trades, int):
            bar["trades"] = trades
        for name in _DELTA_FIELDS:
            value = getattr(row, name, None)  # absent on kline rows -> null, never "0"
            bar[name] = value if isinstance(value, str) else None
        bar["cvd"] = None  # not persisted per bar (24 §3.1); never fabricated
    return bar


def build_meta(
    *,
    count: int,
    next_cursor: str | None,
    sources: Sequence[str],
    recording_started_at_us: int | None,
    generated_at_us: int,
    coverage_holes: list[dict[str, int]] | None = None,
) -> dict[str, object]:
    meta: dict[str, object] = {
        "next_cursor": next_cursor,
        "has_more": next_cursor is not None,
        "count": count,
        "sources": list(sources),
        "recording_started_at": (
            iso_us(recording_started_at_us) if recording_started_at_us is not None else None
        ),
        "generated_at": iso_us(generated_at_us),
    }
    if coverage_holes is not None:
        meta["coverage_holes"] = coverage_holes
    return meta


def kline_response(
    *, symbol: str, interval: str, bar_type: str, bars: list[dict[str, object]],
    meta: dict[str, object],
) -> Response:  # fmt: skip
    """200 `KlineResponse`, or `422 response_too_large` past the ceiling (never truncated)."""
    body = orjson.dumps(
        {"symbol": symbol, "interval": interval, "bar_type": bar_type, "bars": bars, "meta": meta}
    )
    if len(body) > RESPONSE_MAX_BYTES:
        return problem(
            422,
            "response_too_large",
            "Response too large",
            "This page of bars is larger than the server sends at once; request a smaller limit.",
        )
    return Response(content=body, status_code=200, media_type="application/json")


__all__ = [
    "BarRowLike",
    "InvalidCursor",
    "build_meta",
    "decode_cursor",
    "encode_cursor",
    "iso_us",
    "kline_response",
    "problem",
    "serialize_bar",
]
