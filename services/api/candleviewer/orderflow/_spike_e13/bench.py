"""E13-K01 SPIKE bench (throwaway). Run from services/api: python -m candleviewer.orderflow._spike_e13.bench <parity.json>

Bars come from the TS dump (same seeded synthetic set) so both sides measure identical input.
Single process, gc disabled, fastest/median of N, tracemalloc for memory.
"""

from __future__ import annotations

import gc
import json
import statistics
import sys
import time
import tracemalloc

from .kernels import NP, STREAM, Bar


def main() -> None:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
    allb = [Bar(b["t"], b["o"], b["h"], b["l"], b["c"], b["v"]) for b in d["synthetic100k"]["bars"]]
    gc.disable()
    rows = []
    for n in (1_000, 10_000, 100_000):
        bars = allb[:n]
        for name, fn in STREAM.items():
            reps = 5 if n < 100_000 else 3
            st = [_t(lambda: fn(bars)) for _ in range(reps)]
            npt = [_t(lambda: NP[name](bars)) for _ in range(reps)] if name in NP else [float("nan")]
            # incremental per closed bar ~ stream full / n (O(1) recurrence; measured as amortised)
            rows.append({"indicator": name, "bars": n, "py_stream_ms": statistics.median(st), "py_numpy_ms": statistics.median(npt), "py_incr_us_per_bar": statistics.median(st) * 1000 / n})
    tracemalloc.start()
    keep = [fn(allb) for fn in STREAM.values()]
    cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    gc.enable()
    print(json.dumps({"rows": rows, "four_stream_100k_mem_mb": cur / 2**20, "peak_mb": peak / 2**20, "n": len(keep)}, indent=1))


def _t(f: object) -> float:
    t0 = time.perf_counter()
    f()  # type: ignore[operator]  # spike harness
    return (time.perf_counter() - t0) * 1000


if __name__ == "__main__":
    main()
