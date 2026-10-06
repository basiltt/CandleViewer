"""E12-K01 harness. Run from `services/api` (seeded, deterministic, no network):

    PYTHONPATH=. python -m bench.renko_rebuild.run --rows 1000000 --out /tmp/e12k01.json

Measures (Q2) per-builder rebuild of 1M trades read from a Parquet symbol-day (cold-path stand-in,
no live QuestDB here), peak RSS per builder (fresh subprocess each), and cancellation latency of
three strategies; checks BI-4/BI-5 for the prototypes and the ATR-drift counter-example (Q1).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import random
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import psutil
import pyarrow.parquet as pq

from . import atr, builders, corpus

PARAMS = {  # tuned so 1M prints yield a few thousand-100k bars on the synthetic day
    "time": 60_000_000,  # 1 m (us)
    "tick": 1_000,
    "volume": 5_000,  # lots
    "range": 20,  # ticks
    "delta": 2_000,  # lots
    "renko": 10,  # ticks
}


def _batches(path: Path, chunk: int) -> Any:
    return pq.ParquetFile(path).iter_batches(batch_size=chunk)


def _feed(b: builders.Builder, batch: Any) -> None:
    ts = batch.column("ts_us").to_pylist()
    px = batch.column("price_ticks").to_pylist()
    q = batch.column("qty_lots").to_pylist()
    s = batch.column("is_buy").to_pylist()
    on = b.on_trade
    for i in range(len(ts)):
        on(ts[i], px[i], q[i], s[i])


def rebuild_sync(path: Path, kind: str, chunk: int = 65_536) -> tuple[builders.Builder, int, float]:
    """Full rebuild; returns (builder, rows, read_seconds). Read and build are timed separately."""
    b = builders.make(kind, PARAMS[kind])
    rows, read_s = 0, 0.0
    it = iter(_batches(path, chunk))
    while True:
        t = time.perf_counter()
        batch = next(it, None)
        read_s += time.perf_counter() - t
        if batch is None:
            break
        _feed(b, batch)
        rows += batch.num_rows
    b.finish()
    return b, rows, read_s


def child(path: Path, kind: str) -> None:
    proc = psutil.Process()
    t = time.perf_counter()
    b, rows, read_s = rebuild_sync(path, kind)
    wall = time.perf_counter() - t
    info = proc.memory_info()
    peak = getattr(info, "peak_wset", info.rss)
    print(
        json.dumps(
            {
                "kind": kind,
                "rows": rows,
                "bars": len(b.out),
                "wall_s": wall,
                "read_s": read_s,
                "build_s": wall - read_s,
                "rows_per_s": rows / wall,
                "peak_rss_mb": peak / 1e6,
            }
        )
    )


def measure_builders(path: Path, repeats: int) -> list[dict[str, Any]]:
    out = []
    for kind in builders.KINDS:
        runs = []
        for _ in range(repeats):
            cp = subprocess.run(  # noqa: S603 - fixed argv, our own module
                [
                    sys.executable,
                    "-m",
                    "bench.renko_rebuild.run",
                    "--child",
                    kind,
                    "--path",
                    str(path),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            runs.append(json.loads(cp.stdout.strip().splitlines()[-1]))
        runs.sort(key=lambda r: r["wall_s"])
        out.append(runs[len(runs) // 2])  # median run
    return out


# ---- cancellation strategies -------------------------------------------------------------------
class Sink:
    """Stand-in for `bars_*`: rows become visible only on `commit()` (atomic publish)."""

    def __init__(self) -> None:
        self.rows: list[Any] = []

    def commit(self, bars: list[Any]) -> None:
        self.rows.extend(bars)


async def strat_a_task_cancel(path: Path, chunk: int, delay: float) -> tuple[float, int]:
    """A: builder runs ON the loop, one await per chunk (streaming-cursor shape); task.cancel()."""
    sink = Sink()

    async def run() -> None:
        b = builders.make("renko", PARAMS["renko"])
        for batch in _batches(path, chunk):
            await asyncio.sleep(0)  # the cursor's await point
            _feed(b, batch)
        b.finish()
        sink.commit(b.out)

    task = asyncio.ensure_future(run())
    due = time.perf_counter() + delay
    await asyncio.sleep(delay)  # wakes only after the on-loop chunk in flight finishes
    t = due  # latency counts from the INTENDED cancel instant, i.e. includes the loop stall
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    return time.perf_counter() - t, -1 if sink.rows else 0  # -1: finished before cancel landed


async def strat_a2_task_cancel_thread(path: Path, chunk: int, delay: float) -> tuple[float, int]:
    """A2 (anti-pattern): to_thread rebuild + task.cancel(); the thread keeps running."""
    sink = Sink()
    done = threading.Event()

    def work() -> None:
        b, _, _ = rebuild_sync(path, "renko", chunk)
        sink.commit(b.out)  # zombie commit: partial/unwanted rows land after cancel
        done.set()

    task = asyncio.ensure_future(asyncio.to_thread(work))
    await asyncio.sleep(delay)
    t = time.perf_counter()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    awaited = time.perf_counter() - t  # cancel "returns" fast...
    await asyncio.to_thread(done.wait)
    return max(awaited, time.perf_counter() - t), len(sink.rows)  # ...but work stops only here


async def strat_b_token(path: Path, chunk: int, delay: float) -> tuple[float, int]:
    """B: chunked pull loop in a worker thread; token checked per chunk and per 4096 rows."""
    sink = Sink()
    cancel = threading.Event()
    stopped = threading.Event()

    def work() -> None:
        try:
            b = builders.make("renko", PARAMS["renko"])
            for batch in _batches(path, chunk):
                if cancel.is_set():
                    return
                step = 4096
                n = batch.num_rows
                for lo in range(0, n, step):
                    if cancel.is_set():
                        return
                    _feed(b, batch.slice(lo, step))
            b.finish()
            sink.commit(b.out)
        finally:
            stopped.set()

    fut = asyncio.ensure_future(asyncio.to_thread(work))
    await asyncio.sleep(delay)
    t = time.perf_counter()
    cancel.set()
    await fut
    return time.perf_counter() - t, -1 if sink.rows else 0


def measure_cancel(path: Path, trials: int, rng: random.Random) -> list[dict[str, Any]]:
    res = []
    t0 = time.perf_counter()
    rebuild_sync(path, "renko")
    base = time.perf_counter() - t0  # cancel lands at 20-80% of a full renko rebuild
    for name, fn, chunks in (
        ("A_task_cancel_on_loop", strat_a_task_cancel, (8_192, 65_536, 262_144)),
        ("A2_task_cancel_to_thread", strat_a2_task_cancel_thread, (65_536,)),
        ("B_token_chunked_thread", strat_b_token, (8_192, 65_536, 262_144)),
    ):
        for chunk in chunks:
            lats, leaked = [], 0
            for _ in range(trials):
                lat, n = asyncio.run(fn(path, chunk, base * rng.uniform(0.15, 0.6)))
                if n < 0:  # rebuild already committed: not a cancellation sample
                    continue
                lats.append(lat * 1000)
                leaked += n
            lats.sort()
            if not lats:
                continue
            res.append(
                {
                    "strategy": name,
                    "baseline_rebuild_s": base,
                    "chunk_rows": chunk,
                    "trials": trials,
                    "p50_ms": lats[len(lats) // 2],
                    "max_ms": lats[-1],
                    "leaked_rows": leaked,
                }
            )
    return res


# ---- BI-4 / BI-5 / ATR ---------------------------------------------------------------------------
def _rows(cols: dict[str, Any], n: int) -> list[tuple[int, int, int, bool]]:
    return list(
        zip(
            cols["ts_us"][:n].tolist(),
            cols["price_ticks"][:n].tolist(),
            cols["qty_lots"][:n].tolist(),
            cols["is_buy"][:n].tolist(),
            strict=True,
        )
    )


def check_invariants(cols: dict[str, Any], rng: random.Random, n: int = 50_000) -> dict[str, Any]:
    trades = _rows(cols, n)
    res: dict[str, Any] = {}
    for kind in builders.KINDS:
        full = builders.make(kind, PARAMS[kind])
        for t in trades:
            full.on_trade(*t)
        full.finish()
        again = builders.make(kind, PARAMS[kind])
        for t in trades:
            again.on_trade(*t)
        again.finish()
        bi4 = full.out == again.out
        bi5 = True
        for _ in range(20):
            cut = rng.randrange(1, n)
            a = builders.make(kind, PARAMS[kind])
            for t in trades[:cut]:
                a.on_trade(*t)
            snap = a.snapshot()
            b = builders.make(kind, PARAMS[kind])
            b.out = list(a.out)
            b.restore(snap)
            for t in trades[cut:]:
                b.on_trade(*t)
            b.finish()
            bi5 = bi5 and b.out == full.out
        vol = sum(x[6] for x in full.out)
        res[kind] = {"BI-4": bi4, "BI-5": bi5, "BI-1": vol == sum(t[2] for t in trades)}
    return res


def atr_experiment(cols: dict[str, Any], rng: random.Random, n: int = 400_000) -> dict[str, Any]:
    """Frozen-ATR renko is BI-4/BI-5 safe; live-drifting ATR is not (restart loses the history)."""
    trades = _rows(cols, n)
    warm, live = trades[: n // 4], trades[n // 4 :]
    brick = atr.resolve_atr_ticks(warm, 14)
    full = builders.RenkoBuilder(brick)
    for t in live:
        full.on_trade(*t)
    cut_ok = True
    for _ in range(10):
        cut = rng.randrange(1, len(live))
        a = builders.RenkoBuilder(brick)
        for t in live[:cut]:
            a.on_trade(*t)
        b = builders.RenkoBuilder(brick)
        b.out = list(a.out)
        b.restore(a.snapshot())
        for t in live[cut:]:
            b.on_trade(*t)
        cut_ok = cut_ok and b.out == full.out

    # Drifting: brick = live ATR of trailing 1m bars, recomputed on every minute close.
    def drifting(seq: list[tuple[int, int, int, bool]], warm_seq: list[Any]) -> list[Any]:
        out: list[Any] = []
        bld = builders.RenkoBuilder(brick)
        minute = -1
        hist = list(warm_seq)
        for t in seq:
            m = t[0] // atr.MIN_US
            if m != minute:
                minute = m
                try:
                    bld.b = atr.resolve_atr_ticks(hist[-20_000:], 14)
                except ValueError:
                    pass
            hist.append(t)
            bld.on_trade(*t)
        out.extend(bld.out)
        return out

    d_full = drifting(live[:120_000], warm)
    cut = 60_000
    # restart at `cut` with only the live tail available (history not replayed) -> different sizes
    restarted = drifting(live[cut:120_000], [])
    d_resumed_prefix = drifting(live[:cut], warm)
    drift_equiv = d_resumed_prefix + restarted == d_full
    return {
        "frozen_brick_ticks": brick,
        "frozen_bricks": len(full.out),
        "frozen_BI-4_BI-5": cut_ok,
        "drifting_BI-5_when_history_not_replayed": drift_equiv,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=1_000_000)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--trials", type=int, default=15)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--child")
    ap.add_argument("--path", type=Path)
    a = ap.parse_args()
    if a.child:
        child(a.path, a.child)
        return
    rng = random.Random(corpus.SEED)  # noqa: S311 - seeded, non-crypto by design
    cols = corpus.synth_day(a.rows)
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "trades.parquet"
        corpus.write_parquet(cols, path)
        report = {
            "hardware": {
                "cpu": platform.processor(),
                "logical_cpus": psutil.cpu_count(),
                "ram_gb": round(psutil.virtual_memory().total / 2**30, 1),
                "python": platform.python_version(),
                "os": platform.platform(),
            },
            "rows": a.rows,
            "seed": corpus.SEED,
            "parquet_mb": path.stat().st_size / 1e6,
            "source": "synthetic-from-corpus parquet (no live QuestDB; see ADR-0014)",
            "builders": measure_builders(path, a.repeats),
            "cancel": measure_cancel(path, a.trials, rng),
            "invariants": check_invariants(cols, rng),
            "atr": atr_experiment(cols, rng),
        }
    text = json.dumps(report, indent=2)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
