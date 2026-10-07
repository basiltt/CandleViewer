"""Range reads and stale-`build_version` handling for `bars_*` (E12-T02, #345).

`read_bars` returns oldest->newest with a cursor (the last row's `ts`), parameterised queries only
(`symbol`/`bar_param` come from the client). Rows whose `row_checksum` does not verify are
dropped and counted (SR-E12-11). Rows at an older `build_version` than the running code are
served as-is and a rebuild is scheduled **once** per `(symbol, spec_hash)` window, not per poll.
"""

from __future__ import annotations

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
bars_checksum_failures_total = Counter(
    "bars_checksum_failures_total", "Rows dropped on read because row_checksum did not verify."
)


class RowFetcher(Protocol):
    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]: ...


@dataclass(frozen=True, slots=True)
class BarPage:
    rows: list[dict[str, object]]
    next_cursor: int | None  # ts (µs) to pass as `after_ts_us`; None = no more rows
    stale: bool  # served from rows below the current build_version (meta.sources)


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


class BarReader:
    def __init__(
        self,
        conn: RowFetcher,
        schedule_rebuild: Callable[[str, str, int, int], Awaitable[None]],
    ) -> None:
        self._conn = conn
        self._schedule = schedule_rebuild
        self._scheduled: set[tuple[str, str, int, int]] = set()

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
        rows: list[dict[str, object]] = []
        for r in raw:
            if r.get("row_checksum") is not None and r["row_checksum"] != row_checksum(r):
                bars_checksum_failures_total.inc()
                _log.error("bars_row_checksum_mismatch", symbol=symbol, ts=r.get("ts"))
                continue
            rows.append(r)
        current = BUILD_VERSIONS[spec.kind]
        stale = any(int(str(r.get("build_version") or 0)) < current for r in rows)
        if stale:
            bars_stale_build_version_total.inc()
            key = (symbol, spec.spec_hash, from_us, to_us)
            if key not in self._scheduled:
                self._scheduled.add(key)
                await self._schedule(*key)
        more = len(raw) == limit
        cursor = int(str(raw[-1]["ts"])) if more and raw else None
        return BarPage(rows=rows, next_cursor=cursor, stale=stale)
