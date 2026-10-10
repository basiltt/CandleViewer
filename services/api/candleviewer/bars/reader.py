"""Range reads and stale-`build_version` handling for `bars_*` (E12-T02, #345).

`read_bars` returns oldest->newest with a cursor (the last row's `ts`), parameterised queries only
(`symbol`/`bar_param` come from the client). Rows whose `row_checksum` does not verify are
dropped and counted (SR-E12-11). Rows at an older `build_version` than the running code are
served as-is and a rebuild is scheduled **once** per `(symbol, spec_hash)` window, not per poll.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final, Protocol

import structlog

from candleviewer.bars.metrics import bars_tape_read_degraded_total
from candleviewer.bars.models import BarSpec
from candleviewer.bars.rows import BUILD_VERSIONS, bar_param_for, row_checksum
from candleviewer.domain.sql_names import column_identifier, ts_param, ts_us_from_row
from candleviewer.observability.metrics import Counter


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


MAX_LIMIT: Final = 50_000
_FAMILIES: Final = frozenset(BUILD_VERSIONS)

bars_stale_build_version_total = Counter(
    "bars_stale_build_version_total", "Reads that found rows below the current build_version."
)
bars_checksum_mismatch_total = Counter(
    "bars_checksum_mismatch_total",
    "Rows treated as an integrity event on read (reason: mismatch | missing).",
    ["table", "reason"],
)
bars_rebuild_scheduled_total = Counter(
    "bars_rebuild_scheduled_total", "Background rebuilds requested (post single-flight/dedup)."
)

#: Rebuild windows are quantised to this grid so a client cannot mint unbounded distinct keys.
WINDOW_GRID_US: Final = 86_400_000_000  # 1 day
MAX_BUCKETS_PER_SERIES: Final = 8  # beyond this, windows collapse into one catch-all bucket
MAX_REGISTRY: Final = 1_024  # SR-E12-05
TTL_S: Final = 300.0
MAX_ATTEMPTS: Final = 5
BACKOFF_BASE_S: Final = 2.0


class RowFetcher(Protocol):
    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]: ...


@dataclass(frozen=True, slots=True)
class BarPage:
    rows: list[dict[str, object]]
    next_cursor: int | None  # ts (µs) to pass as `after_ts_us`; None = no more rows
    stale: bool  # served from rows below the current build_version (meta.sources)
    #: SR-E12-11 (documented choice: marker, not exception): True when rows were withheld for an
    #: integrity failure, so the page is INCOMPLETE and the caller must not cache it as final.
    integrity_degraded: bool = False
    dropped: int = 0  # rows withheld (checksum mismatch or missing)


#: `ts` is primary: the `/market/bars` cursor is a `ts`, so it needs monotonic ts order;
#: `index` only breaks equal-`ts` ties. `generation` is NOT ordered until #2017 moves the cursor to
#: `(generation, index)` (NULL-`index` kline rows and index-reset rebuilds would skip rows).
#: `index` is a QuestDB reserved word: quoted via the shared helper (#2016), never hand-written.
_ORDER_BY = ", ".join(column_identifier(c) for c in ("ts", "index"))


def build_range_query(
    kind: str,
    symbol: str,
    bar_param: str,
    from_us: int,
    to_us: int,
    after_us: int | None,
    limit: int,
) -> tuple[str, tuple[object, ...]]:
    if kind not in _FAMILIES:
        raise ValueError(f"unknown bar kind {kind!r}")
    if not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
    start = from_us if after_us is None else max(from_us, after_us + 1)
    sql = (
        f"SELECT * FROM bars_{kind} WHERE symbol = $1 AND bar_param = $2 "  # noqa: S608  # nosec B608 reason=table-from-closed-allowlist owner=@CandleViewer/backend
        f"AND ts >= $3 AND ts < $4 ORDER BY {_ORDER_BY} LIMIT {int(limit)}"
    )
    # QuestDB 8.x does not count `LIMIT $n` as a bind slot (asyncpg: "server expects 4
    # arguments"), so the validated-int `limit` (1..MAX_LIMIT, checked above) is inlined.
    return sql, (symbol, bar_param, ts_param(start), ts_param(to_us))


@dataclass(slots=True)
class _Rebuild:
    expires: float
    attempts: int = 0
    next_try: float = 0.0
    in_flight: bool = False
    done: bool = False


class RebuildRegistry:
    """Single-flight, bounded, TTL-pruned rebuild scheduling (BR-31, SR-E12-05)."""

    def __init__(
        self,
        schedule: Callable[[str, str, int, int], Awaitable[None]],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._schedule = schedule
        self._clock = clock
        self._entries: OrderedDict[tuple[str, str, int, int], _Rebuild] = OrderedDict()
        self._per_series: dict[tuple[str, str], int] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def _prune(self, now: float) -> None:
        for key in [k for k, e in self._entries.items() if e.expires <= now and not e.in_flight]:
            self._drop(key)

    def _drop(self, key: tuple[str, str, int, int]) -> None:
        del self._entries[key]
        series = key[:2]
        self._per_series[series] -= 1
        if self._per_series[series] <= 0:
            del self._per_series[series]

    def _key(
        self, symbol: str, spec_hash: str, from_us: int, to_us: int
    ) -> tuple[str, str, int, int]:
        lo, hi = from_us // WINDOW_GRID_US, to_us // WINDOW_GRID_US
        key = (symbol, spec_hash, lo, hi)
        if (
            key not in self._entries
            and self._per_series.get((symbol, spec_hash), 0) >= MAX_BUCKETS_PER_SERIES
        ):
            return (symbol, spec_hash, -1, -1)  # catch-all bucket
        return key

    async def request(self, symbol: str, spec_hash: str, from_us: int, to_us: int) -> bool:
        """True if this call started a rebuild; False if deduplicated/backing off/refused."""
        now = self._clock()
        self._prune(now)
        key = self._key(symbol, spec_hash, from_us, to_us)
        entry = self._entries.get(key)
        if entry is None:
            if len(self._entries) >= MAX_REGISTRY:
                return False  # full of live entries: refuse rather than grow
            entry = _Rebuild(expires=now + TTL_S)
            self._entries[key] = entry
            self._per_series[key[:2]] = self._per_series.get(key[:2], 0) + 1
        if entry.in_flight or entry.done or now < entry.next_try or entry.attempts >= MAX_ATTEMPTS:
            return False
        entry.in_flight = True
        try:
            await self._schedule(
                symbol, spec_hash, key[2] * WINDOW_GRID_US, (key[3] + 1) * WINDOW_GRID_US
            )
        except Exception:
            entry.attempts += 1
            entry.next_try = now + BACKOFF_BASE_S * 2 ** (entry.attempts - 1)
            _log().warning(
                "bars_rebuild_schedule_failed", spec_hash=spec_hash, attempts=entry.attempts
            )
            return False
        else:
            entry.done = True
            bars_rebuild_scheduled_total.inc()
            return True
        finally:
            entry.in_flight = False


class BarReader:
    def __init__(
        self,
        conn: RowFetcher,
        schedule_rebuild: Callable[[str, str, int, int], Awaitable[None]],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._conn = conn
        self._rebuilds = RebuildRegistry(schedule_rebuild, clock)

    async def read_bars(
        self,
        symbol: str,
        spec: BarSpec,
        from_us: int,
        to_us: int,
        limit: int,
        *,
        after_us: int | None = None,
    ) -> BarPage:
        sql, params = build_range_query(
            spec.kind, symbol, bar_param_for(spec), from_us, to_us, after_us, limit
        )
        raw = await self._conn.fetch(sql, *params)
        table = f"bars_{spec.kind}"
        rows: list[dict[str, object]] = []
        dropped = 0
        for r in raw:
            reason = _integrity_failure(r)
            if reason is None:
                rows.append(r)
                continue
            dropped += 1
            bars_checksum_mismatch_total.labels(table, reason).inc()
            _log().warning(
                "bars_row_integrity_event", table=table, reason=reason,
                spec_hash=spec.spec_hash, ts=r.get("ts"),
            )  # fmt: skip
        current = BUILD_VERSIONS[spec.kind]
        stale = any(int(str(r.get("build_version") or 0)) < current for r in rows)
        if stale:
            bars_stale_build_version_total.inc()
            await self._rebuilds.request(symbol, spec.spec_hash, from_us, to_us)
        more = len(raw) == limit
        cursor = ts_us_from_row(raw[-1]["ts"]) if more and raw else None
        return BarPage(rows, cursor, stale, integrity_degraded=dropped > 0, dropped=dropped)


@dataclass(frozen=True, slots=True)
class StoredBar:
    """A `bars_*` row in the kline-like shape `api.market_response` serialises.

    Prices stay the stored DOUBLE rendered with `repr` (round-trips exactly, `bars.rows`).
    `turnover` is not a stored column: it is `vwap * volume` computed in `Decimal`, rendered
    the same way.
    """

    ts_us: int
    close_ts_us: int | None
    open: str
    high: str
    low: str
    close: str
    volume: str
    turnover: str
    confirmed: bool
    trades: int
    delta: str | None  # None on kline-sourced rows: no order flow (null, never zero, BR-07)
    min_delta: str | None
    max_delta: str | None
    source: str

    @property
    def tape_built(self) -> bool:
        """Built from recorded trades (`tape`, or `parquet` = restored tape, `SOURCE_RANK`)."""
        return self.source in ("tape", "parquet")


def _num(v: object) -> str:
    return repr(float(str(v)))


def stored_bar(row: dict[str, object]) -> StoredBar:
    close_ts = row.get("close_ts")
    vwap, volume = Decimal(str(row.get("vwap") or 0)), Decimal(str(row.get("volume") or 0))
    source = str(row.get("source") or "tape")  # NULL = pre-0003 legacy row, tape-built
    flow = source != "kline"
    return StoredBar(
        ts_us=ts_us_from_row(row["ts"]),
        close_ts_us=ts_us_from_row(close_ts) if close_ts is not None else None,
        open=_num(row["open"]), high=_num(row["high"]), low=_num(row["low"]),
        close=_num(row["close"]), volume=_num(volume), turnover=repr(float(vwap * volume)),
        confirmed=bool(row.get("is_closed")), trades=int(str(row.get("trade_count") or 0)),
        delta=_num(row.get("delta") or 0) if flow else None,
        min_delta=_num(row.get("min_delta") or 0) if flow else None,
        max_delta=_num(row.get("max_delta") or 0) if flow else None, source=source,
    )  # fmt: skip


class _Window(Protocol):
    @property
    def start_us(self) -> int: ...
    @property
    def end_us(self) -> int: ...


TapeTimeBars = Callable[[str, str, _Window, "int | None"], Awaitable[list[StoredBar]]]


def tape_time_bar_reader(reader: BarReader, *, timeout_s: float) -> TapeTimeBars:
    """`/market/klines` tier (1): tape-built `bars_time` rows for a kline interval code.

    Only tape-built rows are returned (kline-sourced `bars_time` rows are not tape and must not
    claim it). A failing or slow tape tier degrades the response to klines-only (never a 500,
    never a false `tape` claim): `meta.sources` then honestly omits `tape`.

    S2/A2 (#2087 reviews): the catch is deliberately `Exception`, not a driver class list.
    `LazyPgWire.fetch` re-raises raw asyncpg errors (e.g. `UndefinedTableError` when `bars_time`
    does not exist yet), and `bars` may not import `asyncpg` (ADR-0003 import contract), so it
    cannot name `asyncpg.PostgresError`. Cancellation is a `BaseException` and still propagates.
    Every degrade is counted (`bars_tape_read_degraded_total{reason}`) and logged WARN.
    """
    from candleviewer.bars.spec import TIME_INTERVALS  # cycle break: spec imports models

    async def read(symbol: str, interval: str, rng: _Window, limit: int | None) -> list[StoredBar]:
        interval_ms = TIME_INTERVALS.get(interval)
        if interval_ms is None or rng.end_us <= rng.start_us:
            return []
        spec = BarSpec(kind="time", interval_ms=interval_ms)
        try:
            async with asyncio.timeout(timeout_s):
                page = await reader.read_bars(
                    symbol, spec, rng.start_us, rng.end_us, min(limit or MAX_LIMIT, MAX_LIMIT)
                )
        except Exception as exc:  # broad on purpose: see the S2/A2 note in the docstring
            bars_tape_read_degraded_total.labels(reason=_degrade_reason(exc)).inc()
            _log().warning("bars_tape_read_degraded", error=type(exc).__name__)
            return []
        return [b for b in map(stored_bar, page.rows) if b.tape_built]

    return read


def _degrade_reason(exc: Exception) -> str:
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, (OSError, ConnectionError)):
        return "connection"
    return "query_error"


def _integrity_failure(row: dict[str, object]) -> str | None:
    """None if trustworthy. NULL checksum is untrusted unless the row is pre-0003 legacy
    (both `source` and `row_checksum` NULL: 0003 is their first writer)."""
    checksum = row.get("row_checksum")
    if checksum is None:
        return None if row.get("source") is None else "missing"
    return None if checksum == row_checksum(row) else "mismatch"
