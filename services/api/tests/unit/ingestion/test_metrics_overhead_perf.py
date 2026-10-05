"""E08-T06 Performance note: "Observability overhead must stay under 2% CPU
at the target event rate". Measures the per-event cost of the ingestion
instrumentation actually on the trade path (`symbol_label` + a bound
`ingest_events_total` child `.inc()`) and expresses it as a fraction of one
core at the documented burst target (06-performance 4.3: 500 trades/s/symbol,
10 symbols = 5 000 ev/s).

Measured in a fresh interpreter: the suite runs under coverage, whose line
tracer inflates in-process timings ~7x and would measure the tracer, not the
code. Best-of-N suppresses scheduler noise; the figure is printed for the PR.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TARGET_EVENTS_PER_S = 5_000
BUDGET_CORE_FRACTION = 0.02
API_ROOT = Path(__file__).resolve().parents[3]

_PROBE = """
import time
from candleviewer.ingestion.metrics import count_event
best = float("inf")
for _ in range(5):
    t0 = time.perf_counter()
    for _ in range(20_000):
        count_event("trade", "BTCUSDT")
    best = min(best, (time.perf_counter() - t0) / 20_000)
print(best)
"""


def _per_event_s() -> float:
    out = subprocess.run(  # noqa: S603 - fixed argv: this interpreter + a literal probe
        [sys.executable, "-c", _PROBE],
        cwd=API_ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    return float(out.stdout.strip().splitlines()[-1])


def test_ingestion_instrumentation_overhead_under_2pct_core_at_target_rate() -> None:
    per_event = _per_event_s()
    fraction = per_event * TARGET_EVENTS_PER_S
    print(f"instrumentation {per_event * 1e6:.2f} us/event = {fraction:.2%} of a core @ 5k ev/s")
    assert 0 < fraction < BUDGET_CORE_FRACTION
