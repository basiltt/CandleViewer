"""`GET /market/bars` (`22-api-openapi.yaml` `getBars`, E12-T05 #398).

The single REST entry point for every bar type, served from the `bars_<kind>` tables through
`bars.reader.BarReader.read_bars` (parameterised SQL, table from a closed allow-list, checksum
verified). It never constructs a builder and never substitutes exchange klines.

Order of refusal (each before any storage read except where noted):
1. RBAC `marketdata:read` (501 no resolver / 401 / 403).
2. `bar_type`/`param` parsed by E12-T01's `bars.spec.from_wire` plus the SR-E12-03 bounds
   (`bars.limits`): malformed -> 400 `validation_failed`; a type the server cannot build
   (`pnf`, `heikin_ashi`, renko `atr:*` per ADR-0033 R1) -> 422 naming the alternative.
3. Unknown symbol -> 422; storage not composed -> 503.
4. Non-time bars: a window starting before `recording_started_at` -> 422 `no_data_recorded`.
   This is checked **before** the window cap: it is the more specific data-availability fact,
   and the client cannot fix it by paginating (22-api precedence rule).
5. Hard window caps only (SR-E12-02, 22-api paging rule): time bars <= 400 d and <= 250 000
   estimated bars (window / interval), non-time bars
   <= 31 d -> 422 `bar_window_too_large`. Anything narrower is paged by rows: an uncursored
   request is the first page, every read asks for `limit + 1` rows (bounded work), and a
   server-issued `next_cursor` is returned whenever more rows remain.

The cursor is bound to `(bars, symbol, bar_type:param)` (`api.market_response`), so a klines
cursor or one for another series is `invalid_cursor`. Ordering is by `ts` with a `ts` cursor
(ties broken by `"index"`, `bars.reader`). Since migration 0004 (#2016) equal-`ts` rows ARE
reachable: one large print yields bars 0, 1, 2 at one `ts`, and the `ts` cursor steps past
that `ts`, so with `limit=1` bars 1 and 2 are dropped (known gap, #2017).
TODO(#2017): order by `(generation, index)`, put both on every bar, pin the generation.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Final, Protocol

import structlog
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response

from candleviewer.api.market_response import (
    InvalidCursor,
    build_meta,
    cursor_scope,
    decode_cursor,
    encode_cursor,
    kline_response,
    problem,
    serialize_bar,
)
from candleviewer.bars.errors import BarSpecError
from candleviewer.bars.limits import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    MAX_NON_TIME_WINDOW_US,
    MAX_TIME_WINDOW_US,
    MAX_WINDOW_BARS,
    QTY_PARAM_MAX,
    QUERY_TIMEOUT_S,
    RANGE_TICKS_RANGE,
    TICK_PARAM_RANGE,
)
from candleviewer.bars.metrics import (
    bars_endpoint_422_no_data_recorded_total,
    record_page,
    record_param_rejected,
)
from candleviewer.bars.models import BarSpec
from candleviewer.bars.reader import BarPage, stored_bar
from candleviewer.bars.spec import PARAM_MAX_LEN, from_wire

_REQUIRED_PERMISSION: Final = "marketdata:read"
_BAR_TYPES: Final = frozenset(
    {"time", "tick", "volume", "range", "delta", "renko", "pnf", "heikin_ashi"}
)
_TIME_ALTERNATIVE: Final = "use bar_type=time, tick, volume, range, delta or renko with a number"


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class _Principal(Protocol):
    def has(self, permission: str) -> bool: ...


class _Resolver(Protocol):
    def resolve(self, request: Request) -> Any: ...


class BarReaderLike(Protocol):
    async def read_bars(
        self, symbol: str, spec: BarSpec, from_us: int, to_us: int, limit: int,
        *, after_us: int | None = None,
    ) -> BarPage: ...  # fmt: skip


RecordingStart = Callable[[str], Awaitable[int | None]]


class _Rejected(Exception):
    def __init__(self, response: JSONResponse) -> None:
        self.response = response


def _bad_param(reason: str, status: int, detail: str) -> _Rejected:
    record_param_rejected(reason)
    return _Rejected(problem(status, "validation_failed", "Invalid param", detail))


def parse_bar_request(bar_type: str, param: str) -> BarSpec:
    """`(bar_type, param)` -> `BarSpec` or `_Rejected` (400 malformed, 422 unsupported)."""
    if bar_type not in _BAR_TYPES:
        raise _bad_param("invalid", 400, "bar_type is not a supported bar type.")
    if bar_type in ("pnf", "heikin_ashi") or param.startswith("atr:"):
        what = {
            "pnf": "Point-and-figure bars are not available yet",
            "heikin_ashi": "Heikin-Ashi is a chart transform over time bars; use bar_type=time",
        }.get(bar_type, "ATR-sized renko bricks are not available yet (ADR-0033)")
        raise _bad_param("unsupported", 422, f"{what}; {_TIME_ALTERNATIVE}.")
    if len(param) > PARAM_MAX_LEN:
        raise _bad_param("invalid", 400, f"param must be at most {PARAM_MAX_LEN} characters.")
    try:
        spec = from_wire(bar_type, param)
    except BarSpecError:
        # Never echo the client's text back (it may be a probe); name the field and the rule.
        raise _bad_param(
            "invalid", 400, f"param is not valid for bar_type {bar_type}; see the param table."
        ) from None
    value = int(spec.param_value)
    lo, hi = {
        "tick": TICK_PARAM_RANGE, "range": RANGE_TICKS_RANGE, "renko": RANGE_TICKS_RANGE,
        "volume": (1, QTY_PARAM_MAX), "delta": (1, QTY_PARAM_MAX),
    }.get(spec.kind, (1, 2**63))  # fmt: skip
    if not lo <= value <= hi:
        raise _bad_param(
            "out_of_range", 400, f"param for bar_type {bar_type} must be between {lo} and {hi}."
        )
    return spec


def _ts_us(value: str | None) -> int | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp() * 1_000_000)


def _bad(detail: str) -> JSONResponse:
    return problem(400, "validation_failed", "Bad request", detail)


def _window_too_large(detail: str) -> JSONResponse:
    return problem(422, "bar_window_too_large", "Window too large", detail)


def make_market_bars_router(
    reader_provider: Callable[[], BarReaderLike | None],
    *,
    recording_started_at_us: RecordingStart | None = None,
    principal_resolver: _Resolver | None = None,
    symbol_listed: Callable[[str], bool] | None = None,
    now_us: Callable[[], int],
) -> APIRouter:
    """Bind `GET /market/bars`. `reader_provider()` is resolved per request (the bars reader
    exists only once a real QuestDB is composed); `None` -> 503. `symbol_listed=None` fails
    closed (503), never open."""
    router = APIRouter(tags=["market-data"])

    async def _authorize(request: Request) -> None:
        if principal_resolver is None:
            raise _Rejected(problem(501, "internal_error", "Not implemented",
                                    "Session verification is not wired yet."))  # fmt: skip
        got = principal_resolver.resolve(request)
        principal: _Principal | None = await got if inspect.isawaitable(got) else got
        if principal is None:
            raise _Rejected(problem(401, "unauthenticated", "Unauthorized",
                                    "Sign in to read market data."))  # fmt: skip
        if not principal.has(_REQUIRED_PERMISSION):
            detail = f"Reading market data requires {_REQUIRED_PERMISSION}."
            raise _Rejected(problem(403, "forbidden", "Forbidden", detail))

    @router.get("/market/bars")
    async def get_bars(
        request: Request,
        symbol: str,
        bar_type: str,
        param: str,
        from_: str | None = Query(default=None, alias="from"),
        to: str | None = Query(default=None, alias="to"),
        limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
        cursor: str | None = Query(default=None),  # length enforced by decode_cursor (#2087 S1)
        include_open: bool = Query(default=False),
        include_delta: bool = Query(default=True),
    ) -> Response:
        try:
            await _authorize(request)
            spec = parse_bar_request(bar_type, param)
        except _Rejected as rejected:
            return rejected.response
        try:
            start_us, end_us = _ts_us(from_), _ts_us(to)
        except ValueError:
            return _bad("from/to must be RFC 3339 timestamps.")
        if start_us is None:
            return _bad("'from' is required.")
        end_us = now_us() if end_us is None else end_us
        if start_us > end_us:
            return _bad("'from' must not be after 'to'.")
        after_us: int | None = None
        scope = cursor_scope("bars", symbol, f"{bar_type}:{param}")
        if cursor is not None:
            try:
                after_us = decode_cursor(cursor, scope=scope, end_us=end_us, start_us=start_us) - 1
            except InvalidCursor:
                detail = "The cursor is not valid for this request; restart without it."
                return problem(400, "invalid_cursor", "Invalid cursor", detail)
        if symbol_listed is None or (reader := reader_provider()) is None:
            return problem(503, "store_unavailable", "Service unavailable",
                           "Bar storage is not ready yet.")  # fmt: skip
        if not symbol_listed(symbol):
            return problem(422, "validation_failed", "Unprocessable entity",
                           "This symbol is not a listed instrument.")  # fmt: skip
        if spec.kind != "time" and recording_started_at_us is None:
            # #2089 adversarial L3: no recording-start source wired is a server state, not a
            # fact about the data — 503, never a misleading `no_data_recorded`.
            return problem(503, "store_unavailable", "Service unavailable",
                           "Recording metadata is not available yet; retry shortly.")  # fmt: skip
        started = await recording_started_at_us(symbol) if recording_started_at_us else None
        if spec.kind != "time" and (started is None or start_us < started):
            # Precedence: before the window cap (22-api /market/bars).
            bars_endpoint_422_no_data_recorded_total.inc()
            if started is None:
                when = f"{symbol} has no recorded trades yet"
            else:
                begins = datetime.fromtimestamp(started / 1e6, UTC)
                when = f"recording for {symbol} begins {begins:%d %b %Y}"
            return problem(422, "no_data_recorded", "No data recorded",
                           f"{bar_type.capitalize()} bars need recorded trade data; {when}. "
                           "Choose a later window or use time bars.")  # fmt: skip
        span_cap = MAX_TIME_WINDOW_US if spec.kind == "time" else MAX_NON_TIME_WINDOW_US
        span = end_us - max(start_us, (after_us or 0) + 1)
        if span > span_cap:
            days = span_cap // 86_400_000_000
            return _window_too_large(f"A {bar_type} bar window may span at most {days} days.")
        if spec.kind == "time":
            # SR-E12-02 estimate: ceil(window / interval) <= MAX_WINDOW_BARS, before any query.
            width_us = int(spec.param_value) * 1000
            if -(-span // width_us) > MAX_WINDOW_BARS:
                return _window_too_large(
                    f"The window holds more than {MAX_WINDOW_BARS:,} {param}-minute bars; "
                    "narrow from/to."
                )
        # Non-time bars: SR-E12-02 also asks for a pre-query estimate from the stored print
        # count. No trade-count read exists yet, so that estimate is NOT enforced here; the
        # 31 d cap plus `limit + 1` rows per read bounds the work of this request, but not the
        # total series a client can page through. TODO(#2093): stored-print-count estimate.
        try:
            async with asyncio.timeout(QUERY_TIMEOUT_S):
                page = await reader.read_bars(symbol, spec, start_us, end_us, limit + 1,
                                              after_us=after_us)  # fmt: skip
        except (TimeoutError, OSError, ConnectionError):
            return problem(503, "store_unavailable", "Service unavailable",
                           "Bar storage did not answer in time; retry shortly.")  # fmt: skip
        # `has_more` comes from the RAW fetch (#2089 adversarial M1): `read_bars` withholds
        # checksum-failed rows (`page.dropped`) but reports `next_cursor` = the ts of the
        # (limit+1)-th raw row whenever the fetch was full. That row is the next page's first,
        # so a dropped row (even the page's last) is stepped over, never ends the series.
        resume = page.next_cursor
        rows = [stored_bar(r) for r in page.rows]
        if resume is not None:
            kept = [r for r in rows if r.ts_us < resume]  # the extra row opens the next page
            if kept or not rows:
                rows = kept
            else:
                # Every fetched row shares the resume ts (equal-ts rows filling the
                # page): progress must be strict, so serve the page and step past that ts.
                # Its remaining siblings are skipped. TODO(#2017): resume by (generation, index).
                rows = rows[:limit]
                resume = rows[-1].ts_us + 1
        if not include_open:
            rows = [r for r in rows if r.confirmed]  # only the newest bar can be forming
        next_cursor = encode_cursor(scope, resume) if resume is not None else None
        sources = (["tape"] if any(r.tape_built for r in rows) else []) + (
            ["questdb"] if any(not r.tape_built for r in rows) else [])  # fmt: skip
        record_page("bars", len(rows), sources)
        _log().info("market_bars_served", symbol=symbol, bar_type=bar_type,
                    spec_hash=spec.spec_hash, tiers=sources, rows=len(rows))  # fmt: skip
        meta = build_meta(count=len(rows), next_cursor=next_cursor, sources=sources,
                          recording_started_at_us=started, generated_at_us=now_us())  # fmt: skip
        return kline_response(
            symbol=symbol, interval=param, bar_type=bar_type,
            bars=[serialize_bar(r, include_delta=include_delta) for r in rows], meta=meta,
        )  # fmt: skip

    return router


__all__ = ["BarReaderLike", "RecordingStart", "make_market_bars_router", "parse_bar_request"]
