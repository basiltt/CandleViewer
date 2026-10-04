"""E35-Q02 property suite: generated IR documents round-trip across every editor hop.

Run: ``uv run pytest tests/rules/roundtrip -q --no-cov -s`` (see docs/qa/e35-roundtrip-suite.md).

* ``CV_ROUNDTRIP_EXAMPLES`` - documents per run (default 10 000, the US-RULE-001 NFR floor).
* ``CV_ROUNDTRIP_SEED`` - base seed (default: fresh, always printed); export it to replay a run.
* ``CV_ROUNDTRIP_WORKERS`` - worker processes (default: CPU count, max 8).
* ``CV_ROUNDTRIP_DB`` - Hypothesis example database (default
  ``services/api/.hypothesis/roundtrip``); CI caches it so a failure found once is replayed
  on every later run.
"""

from __future__ import annotations

import os
import random
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings

from candleviewer.rules.ir import Rule
from tests.rules.roundtrip.shard import run_shard
from tests.rules.roundtrip.strategies import any_rule, form_rule

EXAMPLES = int(os.environ.get("CV_ROUNDTRIP_EXAMPLES", "10000"))
SEED = int(os.environ.get("CV_ROUNDTRIP_SEED", str(random.SystemRandom().randrange(2**31))))
WORKERS = max(1, int(os.environ.get("CV_ROUNDTRIP_WORKERS", str(min(8, os.cpu_count() or 1)))))
DB = os.environ.get("CV_ROUNDTRIP_DB", str(Path(__file__).parents[3] / ".hypothesis/roundtrip"))


def plan(total: int, workers: int, base_seed: int) -> list[tuple[str, int, int]]:
    """Two-thirds full grammar, one-third form subset, split evenly over workers; exact total."""
    out: list[tuple[str, int, int]] = []
    for kind, n in (("any", total * 2 // 3), ("form", total - total * 2 // 3)):
        for w in range(workers):
            share = n // workers + (1 if w < n % workers else 0)
            if share:
                out.append((kind, share, base_seed + 1000 * (kind == "form") + w))
    return out


def test_roundtrip_plan_splits_the_exact_document_count() -> None:
    p = plan(10_000, 7, 5)
    assert sum(n for _, n, _ in p) == 10_000
    assert len({s for *_, s in p}) == len(p)  # every shard has its own seed


@pytest.mark.roundtrip
def test_roundtrip_ten_thousand_generated_documents_round_trip() -> None:
    """Scenario: Ten thousand generated documents round-trip."""
    started = time.monotonic()
    shards = plan(EXAMPLES, WORKERS, SEED)
    print(f"\n[roundtrip] seed={SEED} workers={WORKERS} target={EXAMPLES}")
    total = 0
    try:
        with ProcessPoolExecutor(max_workers=WORKERS) as pool:
            futures = [pool.submit(run_shard, k, n, s, DB) for k, n, s in shards]
            for (kind, _, s), f in zip(shards, futures, strict=True):
                done, secs = f.result()
                total += done
                print(
                    f"[roundtrip] shard kind={kind} seed={s} documents={done} elapsed_s={secs:.1f}"
                )
    finally:
        print(
            f"[roundtrip] seed={SEED} documents={total} elapsed_s={time.monotonic() - started:.1f}"
        )
    assert total >= EXAMPLES, f"only {total} documents generated (NFR floor {EXAMPLES})"


@pytest.mark.parametrize("strategy", [any_rule, form_rule], ids=["any", "form"])
def test_roundtrip_generated_documents_are_schema_valid(strategy: Any) -> None:
    """Guards the generator: invalid documents would only exercise the validator."""

    @settings(max_examples=50, deadline=None, database=None)
    @given(strategy)
    def prop(doc: dict[str, Any]) -> None:
        Rule.model_validate(doc)

    prop()
