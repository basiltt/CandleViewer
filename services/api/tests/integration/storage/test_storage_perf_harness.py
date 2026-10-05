"""E07-Q03 storage perf harness against the REAL engine (CI `integration` job).

Every measurement here drives shipped code against a real QuestDB 8.1.1
container (testcontainers, same fixture as E07-T03):

- ingest stress: real `IlpWriter` -> real ILP/TCP socket -> QuestDB; the
  socket's write-buffer high-water is lowered so `drain()` blocks on QuestDB's
  own read rate (genuine backpressure, not a throttled fake). Backpressure
  onset = first moment the writer's buffered rows reach its bound (the
  queue high-watermark event). Zero drops = row count after WAL apply.
- reaper loop lag: real `Reaper.run()` (E07-T05) with an injected clock, its
  `StorageOps` port backed by real `table_partitions()` / `DROP PARTITION`.
- 24 h growth: the recorded fixture `packages/fixtures/raw/synthetic_sample.jsonl`
  replayed cyclically (time-shifted) over 10 min of fixture time at max speed
  through the real writer; bytes from `table_partitions().diskSize`.
- cold vs warm: fresh PGWire connection + a partition never read before.
  NOT truly cold: the OS page cache cannot be dropped without root in CI,
  and the partition was just written, so its pages may be resident. Reported
  as `cache: "fresh-connection, untouched-partition (OS page cache not dropped)"`.

All results are merged into `build/reports/storage-perf.json` (uploaded by CI)
and compared against `tests/perf/storage/baseline_integration.json`.
"""

from __future__ import annotations

import asyncio
import json
import socket
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import asyncpg
import pytest

from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.questdb.ilp_writer import IlpWriter
from candleviewer.storage.questdb.reader import QuestDbReader
from candleviewer.storage.questdb.repository import QuestDbMarketDataRepository
from candleviewer.storage.questdb.runner import run_migrations
from candleviewer.storage.questdb.schemas import ALL_SCHEMAS
from candleviewer.storage.repositories.rows import TickerRow, TradeRow
from candleviewer.storage.retention.policy import RetentionPolicy, RetentionRule
from candleviewer.storage.retention.ports import Partition, Tier
from candleviewer.storage.retention.reaper import Reaper
from candleviewer.storage.sql_identifiers import sql_string_literal
from tests.integration.storage.test_questdb_hot_tier import (
    DDL_DIR,
    _AsyncpgExecutor,
    _AsyncpgTcpIlpTransport,
    _connect,
    questdb_container,  # noqa: F401 -- pytest fixture re-export
    wait_for_row_count,
)

_REPO = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(_REPO / "tests" / "perf" / "storage"))
from stats import (  # type: ignore[import-not-found]  # noqa: E402  # harness module, on sys.path above
    assert_within_baseline,
    write_report_section,
)

pytestmark = [pytest.mark.integration, pytest.mark.perf]

REPORT = Path(__file__).resolve().parents[3] / "build" / "reports" / "storage-perf.json"
BASELINE = _REPO / "tests" / "perf" / "storage" / "baseline_integration.json"
FIXTURE = _REPO / "packages" / "fixtures" / "raw" / "synthetic_sample.jsonl"
_DAY_US = 86_400_000_000
_NOW = datetime(2026, 9, 1, tzinfo=UTC)
_NOW_US = int(_NOW.timestamp() * 1_000_000)


class _LowWatermarkTransport(_AsyncpgTcpIlpTransport):
    """Real TCP transport to QuestDB with an 8 KiB kernel send buffer and a
    16 KiB asyncio high-water, so `drain()` genuinely waits on QuestDB reading
    the socket. Records each such backpressure event (bytes still queued
    after `write()` above the high-water mark)."""

    HIGH = 16_384

    def __init__(self, host: str, port: int) -> None:
        super().__init__(host, port)
        self.t0 = time.perf_counter()
        self.events: list[tuple[float, int]] = []  # (s since t0, queued bytes)

    async def connect(self) -> None:
        await super().connect()
        assert self._writer is not None
        sock = self._writer.get_extra_info("socket")
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 8_192)
        self._writer.transport.set_write_buffer_limits(high=self.HIGH)

    async def write(self, data: bytes) -> None:
        assert self._writer is not None
        self._writer.write(data)
        queued = self._writer.transport.get_write_buffer_size()
        if queued > self.HIGH:
            self.events.append((time.perf_counter() - self.t0, queued))
        await self._writer.drain()


def _baseline() -> dict[str, float]:
    data: dict[str, float] = json.loads(BASELINE.read_text("utf-8"))["metrics_ms"]
    return data


async def _partitions(conn: asyncpg.Connection, table: str) -> list[dict[str, object]]:
    rows = await conn.fetch(f"SELECT * FROM table_partitions('{table}')")  # noqa: S608  # nosec B608 - test-owned literal
    return [dict(r) for r in rows]


async def _disk_bytes(conn: asyncpg.Connection, table: str) -> int:
    return sum(int(str(p["diskSize"])) for p in await _partitions(conn, table))


async def test_ingest_stress_real_writer_backpressure_and_zero_drops(
    questdb_container: tuple[str, int, int],  # noqa: F811 -- fixture injection
) -> None:
    host, pg_port, ilp_port = questdb_container
    conn = await _connect(host, pg_port)
    # bound > flush_rows so the filling producer always flushes (no self-deadlock);
    # producers arriving while depth is in (bound-batch, bound] must block.
    producers, batch, per_producer, bound = 8, 500, 50_000, 3_000
    total = producers * per_producer
    try:
        await run_migrations(_AsyncpgExecutor(conn), DDL_DIR)
        transport = _LowWatermarkTransport(host, ilp_port)
        writer = IlpWriter(
            transport,
            ALL_SCHEMAS,
            max_queue_rows=bound,
            flush_rows=2_500,
        )
        await writer.start()
        repo = QuestDbMarketDataRepository(writer, QuestDbReader(conn))
        t0 = transport.t0 = time.perf_counter()
        # Writer-side high-watermark: the bounded queue's own depth, sampled
        # after every producer call (the writer flushes at flush_rows, so with
        # flush_rows <= bound - batch the queue-full wait is structurally
        # unreachable; QuestDB backpressure propagates via the socket drain).
        high_water = 0

        async def produce(p: int) -> None:
            for b in range(per_producer // batch):
                base = (p * per_producer) + b * batch
                await repo.write_trades(
                    [
                        TradeRow(
                            ts_us=_NOW_US + base + i,
                            symbol="BTCUSDT",
                            price="65000.5",
                            qty="0.001",
                            side="buy" if i % 2 else "sell",
                            trade_id=f"s{base + i}",
                        )
                        for i in range(batch)
                    ]
                )
                nonlocal high_water
                high_water = max(high_water, writer.queue_depth("trades"))

        async with asyncio.timeout(240):  # bounded (C-2.18): a stall fails, never hangs CI
            await asyncio.gather(*(produce(p) for p in range(producers)))
            await writer.stop()
        elapsed = time.perf_counter() - t0
        onset = transport.events[0] if transport.events else None
        await wait_for_row_count(conn, "trades", total, timeout_s=180.0)
        observed = int(await conn.fetchval("SELECT count() FROM trades"))
        result: dict[str, object] = {
            "submitted_rows": total,
            "rows_after_wal_commit": observed,
            "trade_rows_dropped": total - observed,
            "rows_per_s": round(total / elapsed),
            "queue_bound_rows": bound,
            "queue_high_watermark_rows": high_water,
            "backpressure_events": len(transport.events),
            "backpressure_onset_s": round(onset[0], 4) if onset else None,
            "backpressure_onset_queued_bytes": onset[1] if onset else None,
            "write_errors_total": writer.write_errors_total,
            "engine": "questdb:8.1.1 (testcontainers, CI runner)",
        }
        write_report_section(REPORT, "ingest_stress", result)
        assert observed == total  # zero trade drops, reconciled after WAL apply
        assert onset is not None, "socket never exceeded its high-water: no backpressure exercised"
    finally:
        await conn.close()


class _QuestDbPartitionOps:
    """`StorageOps` port over real QuestDB: inventory via `table_partitions()`,
    drop via `ALTER TABLE ... DROP PARTITION LIST`. Hot tier only."""

    def __init__(self, conn: asyncpg.Connection) -> None:
        self._conn = conn
        self.dropped: list[str] = []

    async def list_partitions(self, symbol: str, stream: StreamKind, tier: Tier) -> list[Partition]:
        if tier != "hot" or stream is not StreamKind.TRADES or symbol != "BTCUSDT":
            return []
        out: list[Partition] = []
        for p in await _partitions(self._conn, "trades"):
            if not p["minTimestamp"]:
                continue
            day = datetime.strptime(str(p["name"]), "%Y-%m-%d").replace(tzinfo=UTC)
            start = int(day.timestamp() * 1_000_000)
            out.append(
                Partition(
                    symbol,
                    stream,
                    "hot",
                    TimeRange(start_us=start, end_us=start + _DAY_US),
                    int(str(p["numRows"])),
                    int(str(p["diskSize"])),
                )
            )
        return out

    async def is_exported_and_verified(self, part: Partition) -> bool:
        return True

    async def drop(self, part: Partition) -> None:
        name = datetime.fromtimestamp(part.range.start_us / 1e6, UTC).strftime("%Y-%m-%d")
        stmt = "ALTER TABLE trades DROP PARTITION LIST " + sql_string_literal(name)
        await self._conn.execute(stmt)
        self.dropped.append(name)


class _Facts:
    async def symbols(self) -> list[str]:
        return ["BTCUSDT"]

    async def pinned_symbols(self) -> set[str]:
        return set()

    async def priority(self, symbol: str) -> int:
        return 0

    async def auto_recorded_symbols(self) -> set[str]:
        return set()

    async def replay_session_for(self, part: Partition) -> str | None:
        return None

    async def has_unexported_journal_trade(self, part: Partition) -> bool:
        return False


class _Disk:
    def free_pct(self) -> float:
        return 50.0


class _Sink:
    def __init__(self) -> None:
        self.n = 0

    async def write(self, action: str, detail: dict[str, str | int]) -> None:
        self.n += 1

    async def emit(self, severity: str, code: str, detail: dict[str, str | int]) -> None:
        self.n += 1

    async def pause(self, symbol: str) -> None:
        return None


async def test_reaper_loop_lag_real_reaper_real_drop_partition(
    questdb_container: tuple[str, int, int],  # noqa: F811 -- fixture injection
) -> None:
    host, pg_port, ilp_port = questdb_container
    conn = await _connect(host, pg_port)
    days, per_day, hot_days = 40, 2_000, 7
    try:
        await run_migrations(_AsyncpgExecutor(conn), DDL_DIR)
        writer = IlpWriter(_AsyncpgTcpIlpTransport(host, ilp_port), ALL_SCHEMAS)
        await writer.start()
        repo = QuestDbMarketDataRepository(writer, QuestDbReader(conn))
        for k in range(1, days + 1):
            day0 = _NOW_US - k * _DAY_US
            await repo.write_trades(
                [
                    TradeRow(day0 + i * 1_000_000, "BTCUSDT", "65000.5", "0.01", "buy", f"r{k}-{i}")
                    for i in range(per_day)
                ]
            )
        await writer.stop()
        await wait_for_row_count(conn, "trades", days * per_day, timeout_s=180.0)

        ops, sink = _QuestDbPartitionOps(conn), _Sink()
        policy = RetentionPolicy([], [RetentionRule(StreamKind.TRADES, hot_days, None)])
        reaper = Reaper(policy, ops, _Facts(), _Disk(), sink, sink, sink, clock=lambda: _NOW)

        lags: list[float] = []
        stop = asyncio.Event()

        async def sampler() -> None:  # event-loop lag: overshoot of a 10 ms sleep
            loop = asyncio.get_running_loop()
            while not stop.is_set():
                t = loop.time()
                await asyncio.sleep(0.01)
                lags.append((loop.time() - t - 0.01) * 1000)

        task = asyncio.create_task(sampler())
        t0 = time.perf_counter()
        async with asyncio.timeout(300):
            report = await reaper.run()
        run_s = time.perf_counter() - t0
        stop.set()
        await task
        expected_drops = days - hot_days  # days k >= 8 end at or before the cutoff
        lags.sort()
        result: dict[str, object] = {
            "partitions_seeded": days,
            "partitions_dropped": len(ops.dropped),
            "run_s": round(run_s, 3),
            "lag_samples": len(lags),
            "lag_max_ms": round(lags[-1], 2) if lags else None,
            "lag_p95_ms": round(lags[int(0.95 * (len(lags) - 1))], 2) if lags else None,
            "threshold_ms": "50-100 (AC); gate uses the committed baseline",
            "engine": "questdb:8.1.1 DROP PARTITION, injected clock",
        }
        write_report_section(REPORT, "reaper_loop_lag", result)
        assert len(report.to_drop) == expected_drops == len(ops.dropped)
        assert lags, "no lag samples: the run never yielded to the loop"
        # DROP PARTITION on a WAL table applies asynchronously: bounded wait.
        await wait_for_row_count(conn, "trades", hot_days * per_day, timeout_s=120.0)
        assert_within_baseline(
            {"reaper_lag_max_ms": _baseline()["reaper_lag_max_ms"]},
            {"reaper_lag_max_ms": lags[-1]},
            abs_slack_ms=25.0,
        )
    finally:
        await conn.close()


def _fixture_events() -> list[dict[str, Any]]:
    return [json.loads(line) for line in FIXTURE.read_text("utf-8").splitlines() if line.strip()]


async def test_storage_growth_fixture_replay_10min_extrapolated_24h(
    questdb_container: tuple[str, int, int],  # noqa: F811 -- fixture injection
) -> None:
    """Replay the recorded fixture cyclically over WINDOW_S of fixture time,
    time-shifted per cycle, at a target rate (Bybit BTCUSDT-class, doc 11.1:
    ~29 trades/s, 10 tickers/s), through the real writer; measure disk bytes."""
    host, pg_port, ilp_port = questdb_container
    window_s, trades_per_s, tickers_per_s = 600, 29, 10
    events = _fixture_events()
    trades = [e["data"] for e in events if e["kind"] == "trade"]
    tickers = [e["data"] for e in events if e["kind"] == "ticker"]
    assert trades and tickers
    conn = await _connect(host, pg_port)
    try:
        await run_migrations(_AsyncpgExecutor(conn), DDL_DIR)
        before = {t: await _disk_bytes(conn, t) for t in ("trades", "tickers")}
        writer = IlpWriter(_AsyncpgTcpIlpTransport(host, ilp_port), ALL_SCHEMAS)
        await writer.start()
        repo = QuestDbMarketDataRepository(writer, QuestDbReader(conn))
        t0 = time.perf_counter()
        n_tr = n_tk = 0
        for sec in range(window_s):
            base = _NOW_US + sec * 1_000_000
            tr_rows: list[TradeRow] = []
            for i in range(trades_per_s):
                d = trades[(sec * trades_per_s + i) % len(trades)]
                tr_rows.append(
                    TradeRow(
                        base + i * 30_000,
                        "BTCUSDT",
                        str(d["price"]),
                        str(d["size"]),
                        str(d["side"]),
                        f"g{sec}-{i}",
                    )
                )
            tk_rows: list[TickerRow] = []
            for i in range(tickers_per_s):
                d = tickers[(sec * tickers_per_s + i) % len(tickers)]
                tk_rows.append(
                    TickerRow(
                        base + i * 100_000,
                        "BTCUSDT",
                        str(d["last_price"]),
                        str(d["last_price"]),
                        str(d["last_price"]),
                        "0.0001",
                        "1000",
                    )
                )
            await repo.write_trades(tr_rows)
            await repo.write_tickers(tk_rows)
            n_tr += len(tr_rows)
            n_tk += len(tk_rows)
        await writer.stop()
        replay_s = time.perf_counter() - t0
        await wait_for_row_count(conn, "trades", n_tr, timeout_s=180.0)
        await wait_for_row_count(conn, "tickers", n_tk, timeout_s=180.0)
        scale = 86_400 / window_s
        streams: dict[str, dict[str, object]] = {}
        per_row: list[float] = []
        for t, n in (("trades", n_tr), ("tickers", n_tk)):
            b = await _disk_bytes(conn, t) - before[t]
            per_row.append(b / n)
            streams[t] = {
                "rows": n,
                "disk_bytes_window": b,
                "bytes_per_row": round(b / n, 1),
                "extrapolated_mb_per_day": round(b * scale / 1e6, 1),
            }
        result: dict[str, object] = {
            "method": (
                f"packages/fixtures/raw/synthetic_sample.jsonl replayed cyclically over "
                f"{window_s}s fixture time at {trades_per_s} trades/s + {tickers_per_s} "
                "tickers/s through the real IlpWriter into QuestDB 8.1.1; disk bytes = "
                "sum(table_partitions().diskSize) delta; linear x144 to 24 h"
            ),
            "replay_wall_s": round(replay_s, 2),
            # diskSize counts preallocated column pages (16 MiB append pages): at this row
            # count the delta is allocation, not data. Flag it rather than publish it.
            "allocation_quantized": any(
                int(str(v["disk_bytes_window"])) % (16 * 1024 * 1024) == 0 for v in streams.values()
            ),
            "streams": streams,
            "measured_on": datetime.now(UTC).date().isoformat(),
            "limitations": (
                "fixture is 8 synthetic events (no recorded Bybit capture in-repo yet), "
                "so column entropy is low; orderbook_deltas/heatmap not replayed (no fixture); "
                "uncompressed QuestDB native format (WAL-applied), not Parquet"
            ),
        }
        write_report_section(REPORT, "storage_growth_24h", result)
        assert all(x > 0 for x in per_row)
    finally:
        await conn.close()


_SHAPE_SQL = (
    "SELECT count(), sum(size), max(price) FROM trades "
    "WHERE symbol = 'BTCUSDT' AND ts >= $1 AND ts < $2"
)


async def _time_query(conn: asyncpg.Connection, day: datetime) -> float:
    t = time.perf_counter()
    # QuestDB's PGWire TIMESTAMP is naive UTC; asyncpg rejects tz-aware here.
    lo = day.astimezone(UTC).replace(tzinfo=None)
    await conn.fetch(_SHAPE_SQL, lo, lo + timedelta(days=1))
    return (time.perf_counter() - t) * 1000


async def test_query_cold_vs_warm_and_baseline_gate(
    questdb_container: tuple[str, int, int],  # noqa: F811 -- fixture injection
) -> None:
    host, pg_port, ilp_port = questdb_container
    n_days, per_day = 12, 20_000
    days = [datetime(2025, 1, 1 + d, tzinfo=UTC) for d in range(n_days)]
    conn = await _connect(host, pg_port)
    try:
        await run_migrations(_AsyncpgExecutor(conn), DDL_DIR)
        writer = IlpWriter(_AsyncpgTcpIlpTransport(host, ilp_port), ALL_SCHEMAS)
        await writer.start()
        repo = QuestDbMarketDataRepository(writer, QuestDbReader(conn))
        for d, day in enumerate(days):
            d0 = int(day.timestamp() * 1_000_000)
            await repo.write_trades(
                [
                    TradeRow(
                        d0 + i * 4_000_000,
                        "BTCUSDT",
                        f"{65000 + i % 50}.5",
                        "0.01",
                        "buy" if i % 3 else "sell",
                        f"q{d}-{i}",
                    )
                    for i in range(per_day)
                ]
            )
        await writer.stop()
        # function-scoped container: the table holds only this test's rows
        await wait_for_row_count(conn, "trades", n_days * per_day, timeout_s=180.0)
    finally:
        await conn.close()

    # "cold": one fresh connection per sample, each querying a partition no query has touched.
    cold: list[float] = []
    for day in days[1:]:
        c = await _connect(host, pg_port)
        try:
            cold.append(await _time_query(c, day))
        finally:
            await c.close()
    warm_conn = await _connect(host, pg_port)
    try:
        await _time_query(warm_conn, days[0])
        warm = sorted([await _time_query(warm_conn, days[0]) for _ in range(30)])
    finally:
        await warm_conn.close()
    warm_p95 = warm[int(0.95 * 29)]
    result: dict[str, object] = {
        "shape": "trades symbol/day aggregate (shape #1 family)",
        "warm_samples": len(warm),
        "warm_p95_ms": round(warm_p95, 3),
        "cold_raw_ms": [round(x, 3) for x in cold],
        "cache": (
            "cold = fresh PGWire connection + partition never queried; OS page cache "
            "NOT dropped (no root in CI) and the partition was just written, so this is "
            "QuestDB-cold, not disk-cold"
        ),
        "engine": "questdb:8.1.1",
    }
    write_report_section(REPORT, "query_cold_warm", result)
    assert_within_baseline(
        {"query_warm_p95_ms": _baseline()["query_warm_p95_ms"]},
        {"query_warm_p95_ms": warm_p95},
        abs_slack_ms=25.0,
    )
