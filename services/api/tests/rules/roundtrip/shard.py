"""One property-suite shard, importable so a process pool can run it (E35-Q02 runtime budget).

The 10 000-document NFR is a per-run count, not a per-process one: the suite splits it across
worker processes (each with a distinct derived seed) to stay inside the 4-minute CI budget.
"""

from __future__ import annotations

import time
from typing import Any

from hypothesis import HealthCheck, Phase, given, seed, settings
from hypothesis.database import DirectoryBasedExampleDatabase

from tests.rules.roundtrip.chain import full_chain
from tests.rules.roundtrip.strategies import any_rule, form_rule

STRATEGIES = {"any": any_rule, "form": form_rule}


def run_shard(kind: str, n: int, shard_seed: int, db_path: str | None) -> tuple[int, float]:
    """Run ``n`` documents; returns (documents generated, seconds). Raises on the first failure."""
    seen = [0]
    db = DirectoryBasedExampleDatabase(db_path) if db_path else None

    @seed(shard_seed)
    @settings(max_examples=n, deadline=None, database=db, print_blob=True,
              suppress_health_check=list(HealthCheck),
              phases=(Phase.explicit, Phase.reuse, Phase.generate, Phase.shrink))  # fmt: skip
    @given(STRATEGIES[kind])
    def prop(doc: dict[str, Any]) -> None:
        seen[0] += 1
        full_chain(doc)

    started = time.monotonic()
    prop()
    return seen[0], time.monotonic() - started
