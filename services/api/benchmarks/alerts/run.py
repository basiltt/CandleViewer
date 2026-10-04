"""Run Q1-Q5; write JSON report. ``python -m benchmarks.alerts.run [out.json]``."""

from __future__ import annotations

import json
import sys
from typing import Any

from benchmarks.alerts.extras import SUPPORTED_TF, guard_cost, storm_histogram
from benchmarks.alerts.harness import corpus, run_option


def main(out: str | None = None, ticks: int = 20_000) -> dict[str, Any]:
    a500 = corpus(500, 500)
    q1 = [run_option(n, a500, ticks).row() for n in ("shared", "separate")]
    c100 = corpus(100, 12)
    q2 = [run_option(n, c100, ticks // 4).row() for n in ("shared", "shared_dedup", "separate")]
    rep = {
        "q1_500_alerts_20_symbols": q1,
        "q2_100_alerts_12_conditions": q2,
        "q3_storm_synthetic": storm_histogram(),
        "q4_timeframes": SUPPORTED_TF,
        "q5_guard": guard_cost(),
        "ticks": ticks,
    }
    if out:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=2)
    return rep


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1] if len(sys.argv) > 1 else None), indent=2))
