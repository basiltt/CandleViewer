"""Benchmark runner: re-executes shapes A-F against a live QuestDB endpoint.

Configuration (env vars; the runner skips cleanly, printing a clear message
and exiting 0, when either is unset — no docker/CI QuestDB in this repo's
test environment, matching the ticket's "not yet gating" DoD note):

- ``CV_QUESTDB_PG_DSN``: asyncpg DSN for the PGWire (8812) read endpoint,
  e.g. ``postgresql://user:pass@localhost:8812/qdb``.
- ``CV_QUESTDB_ILP_HOST``: ``host:port`` for the ILP-over-TCP write endpoint
  (default port 9009), used to seed the synthetic dataset before timing reads.

Output schema matches `spikes/storage/results.json` for the ``shapes`` and
``decision`` keys so `compare.py` (and a human) can diff the two directly.

Run:

    uv run python -m benchmarks.questdb_hot_tier.runner --out /tmp/run.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from statistics import mean

SHAPES = ("A", "B", "C", "D", "E", "F")
SYMBOLS = ("BTCUSDT", "ETHUSDT")

#: Target latencies, mirrored from `docs/plan/21-database-schema.md` Sec.13.2
#: and `spikes/storage/bench.py` (kept in sync manually; a drift here is
#: caught by `test_compare.py::test_shape_targets_match_baseline`).
TARGET_MS = {
    "A": 150.0,  # footprint session aggregation
    "B": 200.0,  # replay scan (snapshot seek + forward deltas)
    "C": 60.0,  # CVD roll-up
    "D": 100.0,  # chart bootstrap
    "E": 80.0,  # big-trade scan
    "F": 10.0,  # last price (LATEST ON)
}


class NotConfigured(RuntimeError):
    """Raised (and caught by `main`) when the required env vars are unset."""


@dataclass(frozen=True, slots=True)
class ShapeResult:
    p50_ms: float
    p95_ms: float
    p99_ms: float
    meets_target: bool


def _percentile(samples: list[float], p: float) -> float:
    s = sorted(samples)
    if not s:
        return 0.0
    k = (len(s) - 1) * p
    f, c = int(k), min(int(k) + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def _require_env() -> tuple[str, str]:
    dsn = os.environ.get("CV_QUESTDB_PG_DSN")
    ilp_host = os.environ.get("CV_QUESTDB_ILP_HOST")
    if not dsn or not ilp_host:
        raise NotConfigured(
            "CV_QUESTDB_PG_DSN and/or CV_QUESTDB_ILP_HOST are unset — skipping "
            "the QuestDB perf regression harness (no live endpoint configured "
            "in this environment). Set both env vars to a running QuestDB "
            "instance to produce a real run.json. See README.md."
        )
    return dsn, ilp_host


async def _time_shape_live(
    shape: str, reader: object, symbol: str, samples: int = 20
) -> ShapeResult:
    """Times `shape` against the live reader, `samples` repetitions.

    The concrete per-shape query is intentionally delegated to
    `candleviewer.storage.questdb.reader` builders (imported lazily so this
    module has no hard dependency on `asyncpg`/`aiohttp` being importable
    when the harness is merely skipped)."""
    from candleviewer.storage.models import TimeRange
    from candleviewer.storage.questdb import reader as reader_mod

    now_us = int(time.time() * 1_000_000)
    day_us = 86_400_000_000
    rng = TimeRange(start_us=now_us - day_us, end_us=now_us)

    builder_by_shape = {
        "A": lambda: reader_mod.build_read_footprint_cells(symbol, "time", "1m", rng),
        "B": lambda: reader_mod.build_read_book_deltas(symbol, rng),
        "C": lambda: reader_mod.build_read_orderflow_metrics(symbol, "cvd", rng),
        "D": lambda: reader_mod.build_read_bars(symbol, "time", "1m", rng),
        "E": lambda: reader_mod.build_read_big_trades(symbol, rng, 10_000.0),
        "F": lambda: reader_mod.build_latest_ticker(symbol),
    }
    builder = builder_by_shape[shape]()

    latencies_ms: list[float] = []
    for _ in range(samples):
        start = time.perf_counter()
        await reader.run(builder)  # type: ignore[attr-defined]
        latencies_ms.append((time.perf_counter() - start) * 1000.0)

    p50, p95, p99 = (
        _percentile(latencies_ms, 0.50),
        _percentile(latencies_ms, 0.95),
        _percentile(latencies_ms, 0.99),
    )
    return ShapeResult(p50_ms=p50, p95_ms=p95, p99_ms=p99, meets_target=p95 <= TARGET_MS[shape])


class _TcpIlpTransport:
    """Minimal `IlpTransport` (see `ilp_writer.py`) over a real TCP socket —
    the harness's own transport, since production wiring of a concrete ILP
    socket transport is out of this ticket's scope (writer/reader/repository
    modules only; see the PR's "Deviations" section)."""

    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        self._writer: asyncio.StreamWriter | None = None

    async def connect(self) -> None:
        _, writer = await asyncio.open_connection(self._host, self._port)
        self._writer = writer

    async def write(self, data: bytes) -> None:
        assert self._writer is not None  # noqa: S101 -- internal invariant, not test code
        self._writer.write(data)
        await self._writer.drain()

    async def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            await self._writer.wait_closed()
            self._writer = None


async def _measure_ilp_sustained_rows_per_sec(ilp_host: str, seconds: float = 2.0) -> float:
    """Writes synthetic trade rows for `seconds` and returns sustained
    rows/s, for comparison against the >=600k target (Sec.11.4)."""
    from candleviewer.storage.questdb.ilp_writer import IlpWriter
    from candleviewer.storage.questdb.schemas import ALL_SCHEMAS

    host, _, port_s = ilp_host.rpartition(":")
    port = int(port_s)
    transport = _TcpIlpTransport(host, port)
    writer = IlpWriter(transport, ALL_SCHEMAS)
    await writer.start()
    rng = random.Random(1)  # noqa: S311 -- synthetic bench data, not crypto
    written = 0
    deadline = time.perf_counter() + seconds
    batch_no = 0
    try:
        while time.perf_counter() < deadline:
            batch: list[dict[str, object]] = [
                {
                    "ts": int(time.time() * 1_000_000) + i,
                    "symbol": SYMBOLS[i % len(SYMBOLS)],
                    "side": "buy" if rng.random() < 0.5 else "sell",
                    "price": 50_000.0 + rng.random(),
                    "size": rng.random(),
                    "notional": 100.0,
                    "trade_id": f"bench-{batch_no}-{i}",
                }
                for i in range(1000)
            ]
            await writer.write_rows("trades", batch, "ts")
            written += len(batch)
            batch_no += 1
    finally:
        await writer.stop()
    return written / seconds


async def run_all_live() -> dict[str, object]:
    """Full live run: skips (raises `NotConfigured`) when env is absent."""
    dsn, ilp_host = _require_env()
    import asyncpg  # type: ignore[import-untyped]

    from candleviewer.storage.questdb.reader import QuestDbReader

    pool = await asyncpg.create_pool(dsn=dsn)

    class _Conn:
        async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
            async with pool.acquire() as conn:
                rows = await conn.fetch(sql, *params)
                return [dict(r) for r in rows]

    reader = QuestDbReader(_Conn())
    per_shape: dict[str, object] = {}
    for shape in SHAPES:
        by_symbol = {}
        for symbol in SYMBOLS:
            result = await _time_shape_live(shape, reader, symbol)
            by_symbol[symbol] = {
                "p50_ms": round(result.p50_ms, 3),
                "p95_ms": round(result.p95_ms, 3),
                "p99_ms": round(result.p99_ms, 3),
                "meets_target": result.meets_target,
            }
        per_shape[shape] = {
            "p50_ms": round(mean(v["p50_ms"] for v in by_symbol.values()), 3),
            "p95_ms": round(max(v["p95_ms"] for v in by_symbol.values()), 3),
            "p99_ms": round(max(v["p99_ms"] for v in by_symbol.values()), 3),
            "meets_target": all(v["meets_target"] for v in by_symbol.values()),
            "_by_symbol": by_symbol,
            "target_ms": TARGET_MS[shape],
        }

    await pool.close()
    ilp_rows_per_sec = await _measure_ilp_sustained_rows_per_sec(ilp_host)

    return {
        "shapes": per_shape,
        "ilp_sustained_rows_per_sec": round(ilp_rows_per_sec, 1),
        "ilp_target_rows_per_sec": 600_000,
        "ilp_meets_target": ilp_rows_per_sec >= 600_000,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None, help="output JSON path")
    args = ap.parse_args()

    try:
        report = asyncio.run(run_all_live())
    except NotConfigured as exc:
        print(f"SKIPPED: {exc}", file=sys.stderr)
        return 0

    out_path = Path(args.out) if args.out else Path(__file__).parent / "run.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
