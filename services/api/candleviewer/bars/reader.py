"""Range reads and stale-`build_version` handling for `bars_*` (E12-T02, #345).

`read_bars` returns oldest->newest with a cursor (the last row's `ts`), parameterised queries only
(`symbol`/`bar_param` come from the client). Rows whose `row_checksum` does not verify are
dropped and counted (SR-E12-11). Rows at an older `build_version` than the running code are
served as-is and a rebuild is scheduled **once** per `(symbol, spec_hash)` window, not per poll.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final, Protocol

import structlog

from candleviewer.bars.models import BarSpec
from candleviewer.bars.rows import BUILD_VERSIONS, bar_param_for, row_checksum
from candleviewer.observability.metrics import Counter

_log = structlog.get_logger(__name__)
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
        f"SELECT * FROM bars_{kind} WHERE symbol = $1 AND bar_param = $2 "  # noqa: S608  # nosec B608 - table from closed allowlist
        "AND ts >= $3 AND ts < $4 ORDER BY ts LIMIT $5"
    )
    return sql, (symbol, bar_param, start, to_us, limit)


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
            _log.warning(
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
            _log.warning(
                "bars_row_integrity_event", table=table, reason=reason,
                spec_hash=spec.spec_hash, ts=r.get("ts"),
            )  # fmt: skip
        current = BUILD_VERSIONS[spec.kind]
        stale = any(int(str(r.get("build_version") or 0)) < current for r in rows)
        if stale:
            bars_stale_build_version_total.inc()
            await self._rebuilds.request(symbol, spec.spec_hash, from_us, to_us)
        more = len(raw) == limit
        cursor = int(str(raw[-1]["ts"])) if more and raw else None
        return BarPage(rows, cursor, stale, integrity_degraded=dropped > 0, dropped=dropped)


def _integrity_failure(row: dict[str, object]) -> str | None:
    """None if trustworthy. NULL checksum is untrusted unless the row is pre-0003 legacy
    (both `source` and `row_checksum` NULL: 0003 is their first writer)."""
    checksum = row.get("row_checksum")
    if checksum is None:
        return None if row.get("source") is None else "missing"
    return None if checksum == row_checksum(row) else "mismatch"
