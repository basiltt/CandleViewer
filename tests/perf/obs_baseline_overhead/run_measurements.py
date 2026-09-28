"""CLI entrypoint: runs the E04-K01 harness across all four configurations,
both label shapes, and the contextvars propagation probe; prints a JSON report.

Usage (from services/api's venv or any interpreter with the deps below):
    python -m tests.perf.obs_baseline_overhead.run_measurements \
        --rate 20000 --duration 120 --repeats 3

Note: the ticket calls for 120s x 3 repeats x 4 configs x 2 label shapes on the
4 vCPU / 8GB reference VPS profile (06-performance-and-load-standard.md §3).
That full matrix takes ~16 minutes; a --quick flag runs a short smoke matrix
for local iteration.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys

from tests.perf.obs_baseline_overhead.harness import (
    Configuration,
    LabelShape,
    measure_contextvars_cost,
    run_pipeline,
    summarize_repeats,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rate", type=int, default=20_000, help="messages/sec")
    parser.add_argument("--duration", type=float, default=120.0, help="seconds per run")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--quick", action="store_true", help="short smoke matrix")
    parser.add_argument("--contextvars-iterations", type=int, default=200_000)
    args = parser.parse_args(argv)

    if args.quick:
        args.rate, args.duration, args.repeats = 2_000, 2.0, 1

    report: dict[str, object] = {
        "rate_per_s": args.rate,
        "duration_s": args.duration,
        "repeats": args.repeats,
    }
    configs_report = []

    for config in Configuration:
        for label_shape in LabelShape:
            if config is Configuration.NONE and label_shape is LabelShape.PRE_BOUND:
                continue  # label shape is meaningless without metrics
            repeats = [
                run_pipeline(
                    config, label_shape, rate_per_s=args.rate, duration_s=args.duration
                )
                for _ in range(args.repeats)
            ]
            summary = summarize_repeats(repeats)
            configs_report.append(
                {
                    "configuration": config.value,
                    "label_shape": label_shape.value,
                    "repeats": [dataclasses.asdict(r) for r in repeats],
                    "summary": summary,
                }
            )

    report["configurations"] = configs_report
    report["contextvars_cost_ns_per_call"] = measure_contextvars_cost(
        args.contextvars_iterations
    )

    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
