"""Ingest, cold-tier, growth and loop-lag measurements (E07-Q03)."""

from __future__ import annotations

import asyncio
import json
import random
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).parent))
from candleviewer.observability import spawn
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.questdb.ilp_writer import IlpWriter
from candleviewer.storage.questdb.schemas import TRADES_SCHEMA
from candleviewer.storage.retention.policy import (
    RetentionPolicy,
    load_defaults,
)
from candleviewer.storage.retention.ports import Partition
from candleviewer.storage.retention.reaper import Reaper
from candleviewer.storage.sql_identifiers import checked_identifier, sql_string_literal

from harness import conditions


class SocketTransport:
    """Real asyncio TCP transport (loopback) implementing IlpTransport."""

    def __init__(self, host: str, port: int) -> None:
        self._addr = (host, port)
        self._w: asyncio.StreamWriter | None = None

    async def connect(self) -> None:
        _, self._w = await asyncio.open_connection(*self._addr)

    async def write(self, data: bytes) -> None:
        assert self._w is not None
        self._w.write(data)
        await self._w.drain()

    async def close(self) -> None:
        if self._w is not None:
            self._w.close()
            await self._w.wait_closed()


class IlpSink:
    """Loopback TCP sink standing in for QuestDB's ILP port. `delay_s` pauses between
    64 KiB reads so the kernel socket buffers fill and drain() really blocks."""

    def __init__(self, delay_s: float = 0.0) -> None:
        self.delay_s = delay_s
        self.lines = 0
        self.bytes = 0
        self._server: asyncio.Server | None = None
        self.port = 0

    async def _handle(self, r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        while chunk := await r.read(65536):
            self.lines += chunk.count(10)
            self.bytes += len(chunk)
            if self.delay_s:
                await asyncio.sleep(self.delay_s)
        w.close()

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        assert self._server is not None
        self._server.close()
        await self._server.wait_closed()


def _trade_rows(rng: random.Random, start: int, n: int) -> list[dict[str, object]]:
    return [
        {
            "symbol": "BTCUSDT",
            "side": "Buy",
            "tick_dir": "PlusTick",
            "trade_id": f"t{start + i}",
            "is_block": False,
            "price": 60000.0 + rng.random(),
            "qty": rng.random(),
            "ts": 1_700_000_000_000_000 + start + i,
        }
        for i in range(n)
    ]


async def run_ingest(
    *,
    seconds: float,
    batch: int,
    drain_delay_s: float = 0.0,
    max_queue_rows: int = 200_000,
    seed: int = 1,
    require_backpressure: bool = False,
) -> dict[str, object]:
    """Push trade rows through the real IlpWriter for `seconds`; report rows/s,
    queue depth, backpressure onset (first time a write_rows call had to wait)
    and the never-drop invariant (submitted == written after stop)."""
    rng = random.Random(seed)
    sink = IlpSink(drain_delay_s)
    await sink.start()
    w = IlpWriter(
        SocketTransport("127.0.0.1", sink.port),
        {"trades": TRADES_SCHEMA},
        max_queue_rows=max_queue_rows,
        rng=random.Random(seed),
    )
    await w.start()
    submitted = 0
    max_depth = 0
    onset: float | None = None
    stop_sampling = False

    async def sample_depth() -> None:
        nonlocal max_depth
        while not stop_sampling:
            max_depth = max(max_depth, w.queue_depth("trades"))
            await asyncio.sleep(0)

    sampler = spawn(sample_depth(), name="perf-sample-depth")
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < seconds:
        rows = _trade_rows(rng, submitted, batch)
        t = time.perf_counter()
        await w.write_rows("trades", rows, "ts")
        waited = time.perf_counter() - t
        submitted += batch
        max_depth = max(max_depth, w.queue_depth("trades"))
        if onset is None and (waited > 0.01 or w.queue_depth("trades") >= max_queue_rows - batch):
            onset = submitted / (time.perf_counter() - t0)
    elapsed = time.perf_counter() - t0
    stop_sampling = True
    await sampler
    await w.stop()
    await asyncio.sleep(0.2)  # let the sink consume what the kernel buffered
    await sink.stop()
    if require_backpressure and (max_depth <= 0 or onset is None):
        raise AssertionError(
            f"stress scenario never backed up: max_queue_depth={max_depth}, onset={onset}"
        )
    return {
        "submitted_rows": submitted,
        "sink_lines_received": sink.lines,
        "sink_bytes_received": sink.bytes,
        "written_rows": w.rows_written_total,
        "rows_per_s": round(submitted / elapsed),
        "max_queue_depth": max_depth,
        "backpressure_onset_rows_s": None if onset is None else round(onset),
        "trade_rows_dropped": submitted - w.rows_written_total,
        "write_errors": w.write_errors_total,
        "target_rows_s": 600_000,
        "conditions": conditions("synthetic-trades", "ilp_writer+loopback-tcp-sink", "n/a"),
    }


def _make_parquet_dir(d: Path, files: int, rows_per_file: int, seed: int) -> None:
    con = duckdb.connect()
    con.execute("SELECT setseed(?)", [(seed % 1000) / 1000.0])
    for i in range(files):
        lo = i * rows_per_file
        target = sql_string_literal((d / f"part-{i:05d}.parquet").as_posix())
        stmt = (
            "COPY (SELECT i::BIGINT ts,'BTCUSDT' symbol,60000+random() price,"
            "random() qty FROM range(?,?) r(i)) TO " + target + " (FORMAT PARQUET)"
        )
        con.execute(stmt, [lo, lo + rows_per_file])
    con.close()


def _scan_ms(d: Path, repeats: int = 10) -> float:
    con = duckdb.connect()
    glob = (d / "*.parquet").as_posix()
    best = float("inf")
    for _ in range(repeats):
        t = time.perf_counter()
        con.execute("SELECT count(*), sum(qty) FROM read_parquet(?)", [glob]).fetchall()
        best = min(best, (time.perf_counter() - t) * 1000)
    con.close()
    return best


def run_cold(seed: int, rows: int = 200_000, small_files: int = 200) -> dict[str, object]:
    """Parquet export MB/s and compaction before/after scan time."""
    tmp = Path(tempfile.mkdtemp(prefix="cvcold-"))
    con = duckdb.connect()
    con.execute("SELECT setseed(?)", [(seed % 1000) / 1000.0])
    con.execute(
        "CREATE TABLE t AS SELECT i::BIGINT ts,'BTCUSDT' symbol,60000+random() price,"
        "random() qty FROM range(?) r(i)",
        [rows],
    )
    out = tmp / "export.parquet"
    t = time.perf_counter()
    target = sql_string_literal(out.as_posix())
    stmt = "COPY t TO " + target + " (FORMAT PARQUET, COMPRESSION ZSTD)"
    con.execute(stmt)
    dt = time.perf_counter() - t
    size = out.stat().st_size
    mb_s = size / 1e6 / dt
    con.close()
    many, one = tmp / "many", tmp / "compacted"
    many.mkdir()
    one.mkdir()
    _make_parquet_dir(many, small_files, max(1, rows // small_files), seed)
    c2 = duckdb.connect()
    c2.execute(
        f"COPY (SELECT * FROM read_parquet('{(many / '*.parquet').as_posix()}')) "
        f"TO '{(one / 'part-00000.parquet').as_posix()}' (FORMAT PARQUET)"
    )
    c2.close()
    before, after = _scan_ms(many), _scan_ms(one)
    return {
        "export": {
            "bytes": size,
            "seconds": round(dt, 4),
            "mb_per_s": round(mb_s, 1),
            "target_mb_s": 200,
            "note": "output size/time; MB/s is compressed bytes written",
            "conditions": conditions(f"synthetic-{rows}rows", "duckdb-parquet-proxy", "warm"),
        },
        "compaction": {
            "small_files": small_files,
            "scan_ms_before": round(before, 3),
            "scan_ms_after": round(after, 3),
            "speedup_x": round(before / after, 2) if after else None,
            "conditions": conditions(f"synthetic-{rows}rows", "duckdb", "warm"),
        },
    }


class _ReaperEnv:
    """Fake StorageOps/RetentionFacts/DiskProbe/AuditWriter/SystemEventSink/RecorderControl
    around an inventory of old partitions; drives the REAL `Reaper` (E07-T05)."""

    def __init__(self, parts: list[Partition]) -> None:
        self.parts = parts
        self.dropped = 0

    async def list_partitions(self, symbol: str, stream: StreamKind, tier: str) -> list[Partition]:
        return [
            p for p in self.parts if p.symbol == symbol and p.stream == stream and p.tier == tier
        ]

    async def is_exported_and_verified(self, p: Partition) -> bool:
        return True

    async def drop(self, p: Partition) -> None:
        self.dropped += 1
        sum(i * i for i in range(500))  # small CPU slice per drop

    async def symbols(self) -> list[str]:
        return sorted({p.symbol for p in self.parts})

    async def pinned_symbols(self) -> set[str]:
        return set()

    async def priority(self, symbol: str) -> int:
        return 0

    async def auto_recorded_symbols(self) -> set[str]:
        return set()

    async def replay_session_for(self, p: Partition) -> str | None:
        return None

    async def has_unexported_journal_trade(self, p: Partition) -> bool:
        return False

    def free_pct(self) -> float:
        return 50.0

    async def write(self, action: str, detail: dict[str, object]) -> None:
        return None

    async def emit(self, severity: str, code: str, detail: dict[str, object]) -> None:
        return None

    async def pause(self, symbol: str) -> None:
        return None


async def measure_loop_lag(
    symbols: int = 20, days: int = 60, interval_s: float = 0.005
) -> dict[str, object]:
    """Event-loop lag sampled while the real `Reaper.run()` purges symbols*days
    old trades partitions. Threshold 50-100 ms."""
    day = 86_400_000_000
    now = datetime(2026, 6, 1, tzinfo=UTC)
    now_us = int(now.timestamp() * 1_000_000)
    parts = [
        Partition(
            f"S{s:03d}",
            StreamKind.TRADES,
            "hot",
            TimeRange(start_us=now_us - (40 + d) * day - day, end_us=now_us - (40 + d) * day),
            100,
            1000,
        )
        for s in range(symbols)
        for d in range(days)
    ]
    env = _ReaperEnv(parts)
    reaper = Reaper(
        RetentionPolicy([], load_defaults()),
        env,
        env,
        env,
        env,
        env,
        env,
        clock=lambda: now,
    )
    lags: list[float] = []
    stop = asyncio.Event()

    async def sampler() -> None:
        while not stop.is_set():
            t = time.perf_counter()
            await asyncio.sleep(interval_s)
            lags.append(max(0.0, (time.perf_counter() - t - interval_s) * 1000))

    task = spawn(sampler(), name="perf-sampler")
    await asyncio.sleep(interval_s * 4)
    t0 = time.perf_counter()
    await reaper.run()
    run_s = time.perf_counter() - t0
    stop.set()
    await task
    mx = max(lags) if lags else 0.0
    return {
        "samples": len(lags),
        "max_lag_ms": round(mx, 2),
        "partitions": len(parts),
        "partitions_dropped": env.dropped,
        "run_seconds": round(run_s, 3),
        "threshold_ms": [50, 100],
        "within_threshold": mx <= 100,
        "conditions": conditions(
            f"synthetic-{len(parts)}-partitions", "real Reaper+fake ops", "n/a"
        ),
    }


_DAY_ROWS = {"trades": 2_500_000, "tickers": 864_000, "orderbook_deltas": 190_000_000}


def _growth_rows(rng: random.Random, stream: str, n: int) -> list[dict[str, object]]:
    """Seeded, realistic-cardinality replay of one stream (price random-walks, ts monotonic)."""
    px = 60000.0
    out: list[dict[str, object]] = []
    for i in range(n):
        px = max(1.0, px + rng.choice((-0.5, 0.0, 0.5)))
        ts = 1_700_000_000_000_000 + i * (86_400_000_000 // _DAY_ROWS[stream])
        if stream == "trades":
            out.append(
                {
                    "symbol": "BTCUSDT",
                    "side": rng.choice(("Buy", "Sell")),
                    "tick_dir": rng.choice(("PlusTick", "MinusTick", "ZeroPlusTick")),
                    "trade_id": f"{rng.getrandbits(64):016x}",
                    "is_block": False,
                    "price": px,
                    "qty": round(rng.expovariate(20), 3),
                    "ts": ts,
                }
            )
        elif stream == "tickers":
            out.append(
                {
                    "symbol": "BTCUSDT",
                    "last_price": px,
                    "bid_price": px - 0.5,
                    "ask_price": px + 0.5,
                    "volume_24h": 1e5 + i,
                    "turnover_24h": 6e9 + i,
                    "open_interest": 8e4,
                    "funding_rate": 0.0001,
                    "next_funding_ts": ts,
                    "ts": ts,
                }
            )
        else:
            out.append(
                {
                    "symbol": "BTCUSDT",
                    "side": rng.choice(("Buy", "Sell")),
                    "action": rng.choice(("update", "delete", "insert")),
                    "price": round(px + rng.randint(-100, 100) * 0.5, 1),
                    "size": round(rng.expovariate(2), 3),
                    "seq": i,
                    "ts": ts,
                }
            )
    return out


def measure_storage_growth(sample_rows: int = 50_000, seed: int = 1) -> dict[str, object]:
    """Replay a seeded sample of each stream through the REAL ILP serializer and a ZSTD
    Parquet write; bytes/row x section 11.1 rows/day = measured GB/day/symbol for the
    streams replayed. Remaining streams stay at the section 11 estimate."""
    from candleviewer.storage.questdb.ilp_writer import serialize_ilp_line
    from candleviewer.storage.questdb.schemas import (
        ORDERBOOK_DELTAS_SCHEMA,
        TICKERS_SCHEMA,
    )

    schemas = {
        "trades": TRADES_SCHEMA,
        "tickers": TICKERS_SCHEMA,
        "orderbook_deltas": ORDERBOOK_DELTAS_SCHEMA,
    }
    tmp = Path(tempfile.mkdtemp(prefix="cvgrowth-"))
    rng = random.Random(seed)
    streams: dict[str, object] = {}
    raw_total = pq_total = 0.0
    for name, schema in schemas.items():
        rows = _growth_rows(rng, name, sample_rows)
        ilp = sum(
            len(
                serialize_ilp_line(
                    schema, {k: v for k, v in r.items() if k != "ts"}, int(str(r["ts"]))
                ).encode()
            )
            + 1
            for r in rows
        )
        f = tmp / f"{name}.jsonl"
        f.write_text(chr(10).join(json.dumps(r) for r in rows), encoding="utf-8")
        out = tmp / f"{name}.parquet"
        con = duckdb.connect()
        con.execute(
            f"COPY (SELECT * FROM read_json_auto('{f.as_posix()}')) TO "
            f"'{out.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
        )
        con.close()
        pq = out.stat().st_size
        per_day = _DAY_ROWS[name]
        raw_gb, pq_gb = (
            ilp / sample_rows * per_day / 1e9,
            pq / sample_rows * per_day / 1e9,
        )
        raw_total += raw_gb
        pq_total += pq_gb
        streams[name] = {
            "ilp_bytes_per_row": round(ilp / sample_rows, 1),
            "parquet_bytes_per_row": round(pq / sample_rows, 1),
            "rows_per_day": per_day,
            "raw_gb_day": round(raw_gb, 3),
            "parquet_gb_day": round(pq_gb, 3),
        }
    return {
        "streams": streams,
        "measured_streams_raw_gb_day": round(raw_total, 2),
        "measured_streams_parquet_gb_day": round(pq_total, 3),
        "doc_estimate_same_streams_parquet_gb_day": round(0.028 + 0.62 + 0.014, 3),
        "basis": f"seeded replay of {sample_rows} rows/stream (trades, tickers, orderbook_deltas)"
        " through real ILP serializer + ZSTD Parquet, scaled to section 11.1 rows/day;"
        " NOT a live 24 h capture; other streams unmeasured",
        "conditions": conditions(
            f"replay-seed{seed}-n{sample_rows}", "ilp-serializer+duckdb-parquet", "n/a"
        ),
    }
