"""Bounded Parquet read path for `/market/klines` (E12 cold tier, issue #2048).

Layout `klines/symbol=<S>/interval=<I>/ym=<YYYY-MM>/part-*.parquet` (`21-database-schema.md`
Sec.5.1). Every path is built by `DatasetRegistry.resolve_partition`, which validates the
symbol/interval/month against a closed charset *before* any join (SR-097), so `../x` never
reaches the filesystem. The scan is bounded: only the months the (already capped) window
touches are opened, only manifest-listed + verified files are read, the DuckDB statement is
fully parameterised, `LIMIT` is pushed down, and the blocking call runs off the event loop
under a timeout (C-2.18) that interrupts the DuckDB connection.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from candleviewer.observability import spawn
from candleviewer.storage.cold.layout import ColdPaths, DatasetRegistry
from candleviewer.storage.cold.manifest import ManifestStore
from candleviewer.storage.cold.observability import LoggingSystemEventSink, SystemEventSink
from candleviewer.storage.cold.scrub import verify_partition
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.models import StreamKind

_MAX_MONTHS = 120
_DEFAULT_MAX_ROWS = 5_100


class ColdKlineReadTimeout(StorageTierUnavailable):
    """The DuckDB kline read exceeded its deadline (route maps this to 503)."""

    code = "COLD_KLINE_READ_TIMEOUT"


@dataclass(frozen=True, slots=True)
class ColdKlineRow:
    """One Parquet kline, shaped like `ingestion.kline_read.KlineRowLike`."""

    ts_us: int
    open: str
    high: str
    low: str
    close: str
    volume: str
    turnover: str
    confirmed: bool
    source: str


def _num(value: object) -> str:
    return format(Decimal(repr(value)), "f") if isinstance(value, float) else str(value)


def months_between(start_us: int, end_us: int) -> list[str]:
    """`YYYY-MM` keys of every month overlapping `[start_us, end_us)`, oldest first."""
    if end_us <= start_us:
        return []
    first = datetime.fromtimestamp(start_us / 1_000_000, tz=UTC)
    last = datetime.fromtimestamp((end_us - 1) / 1_000_000, tz=UTC)
    out: list[str] = []
    y, m = first.year, first.month
    while (y, m) <= (last.year, last.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out[-_MAX_MONTHS:]


class ParquetKlineReader:
    """`ColdKlineReader` (see `ingestion.kline_read`) over the cold lake."""

    def __init__(
        self,
        registry: DatasetRegistry,
        *,
        events: SystemEventSink | None = None,
        timeout_s: float = 5.0,
        max_rows: int = _DEFAULT_MAX_ROWS,
    ) -> None:
        self._registry = registry
        self._events: SystemEventSink = events or LoggingSystemEventSink()
        self._timeout_s = timeout_s
        self._max_rows = max_rows
        self._verified: dict[Path, tuple[int, int]] = {}

    def _partition(self, symbol: str, interval: str, ym: str) -> ColdPaths:
        return self._registry.resolve_partition(
            StreamKind.KLINES, partition_values={"symbol": symbol, "interval": interval, "ym": ym}
        )

    async def _files(self, paths: ColdPaths) -> list[str]:
        entries = await asyncio.to_thread(
            ManifestStore(paths.manifests_dir).read, paths.partition_dir, paths.root
        )
        files = [paths.partition_dir / e.file for e in entries]
        stamps: dict[Path, tuple[int, int]] = {}
        for f in files:
            st = f.stat() if f.is_file() else None
            stamps[f] = (st.st_size, st.st_mtime_ns) if st else (-1, -1)
        if files and any(self._verified.get(f) != stamps[f] for f in files):
            await verify_partition(paths, self._events)
            self._verified.update(stamps)
        return [f.as_posix() for f in files]

    async def __call__(self, symbol: str, interval: str, rng: Any) -> list[ColdKlineRow]:
        lo, hi = int(rng.start_us), int(rng.end_us)
        files: list[str] = []
        # Validation happens inside `_partition` for every component, before any I/O.
        for ym in months_between(lo, hi):
            files.extend(await self._files(self._partition(symbol, interval, ym)))
        if not files:
            return []
        return await self._query(files, lo, hi)

    async def _query(self, files: list[str], lo: int, hi: int) -> list[ColdKlineRow]:
        holder: list[duckdb.DuckDBPyConnection] = []
        task = spawn(
            asyncio.to_thread(_read_rows, files, lo, hi, self._max_rows, holder),
            name="cold-kline-read",
        )
        try:
            async with asyncio.timeout(self._timeout_s):
                return await asyncio.shield(task)
        except TimeoutError as exc:
            for con in holder:
                con.interrupt()
            raise ColdKlineReadTimeout(f"cold kline read exceeded {self._timeout_s}s") from exc


def _read_rows(
    files: list[str],
    lo: int,
    hi: int,
    max_rows: int,
    holder: list[duckdb.DuckDBPyConnection],
    connect: Callable[[], duckdb.DuckDBPyConnection] = lambda: duckdb.connect(":memory:"),
) -> list[ColdKlineRow]:
    con = connect()
    holder.append(con)
    try:
        con.execute("SET TimeZone = 'UTC'")
        table = con.execute(
            "SELECT CAST(epoch_us(ts) AS BIGINT) AS ts_us, open, high, low, close, volume, "
            "turnover, confirmed, source FROM read_parquet($files, hive_partitioning = false) "
            "WHERE ts >= make_timestamptz($lo::BIGINT) AND ts < make_timestamptz($hi::BIGINT) "
            "ORDER BY ts DESC LIMIT $n",
            {"files": files, "lo": lo, "hi": hi, "n": max_rows},
        ).to_arrow_table()
    finally:
        con.close()
    seen: dict[int, ColdKlineRow] = {}
    for r in table.to_pylist():
        seen.setdefault(
            int(r["ts_us"]),
            ColdKlineRow(
                ts_us=int(r["ts_us"]),
                open=_num(r["open"]),
                high=_num(r["high"]),
                low=_num(r["low"]),
                close=_num(r["close"]),
                volume=_num(r["volume"]),
                turnover=_num(r["turnover"]),
                confirmed=bool(r["confirmed"]),
                source=str(r["source"]),
            ),
        )
    return [seen[k] for k in sorted(seen)]


__all__ = ["ColdKlineReadTimeout", "ColdKlineRow", "ParquetKlineReader", "months_between"]
