"""E35-Q02 mutation sanity check: the suite must catch a known canonicalisation defect.

Injects an *unsorted keys* defect into ``canonicalize`` (the canonical JSON keeps insertion order)
and asserts that the property suite (a) fails, (b) shrinks to a minimal reproducing document and
(c) does so inside 60 s. A suite that has silently stopped asserting anything fails this test.
"""

from __future__ import annotations

import json
import time
from typing import Any

import pytest
from hypothesis import HealthCheck, Phase, given, seed, settings

import candleviewer.rules.ir.canonical as canonical
from candleviewer.rules.ir import Rule
from tests.rules.roundtrip.chain import HopMismatch, full_chain
from tests.rules.roundtrip.strategies import any_rule

SHRINK_BUDGET_S = 60.0


def _unsorted_canonicalize(ir: Rule | dict[str, Any]) -> bytes:
    """The injected defect: identical to ``canonicalize`` except ``sort_keys=False``."""
    dumped = canonical._as_rule(ir).model_dump(mode="python")
    view = canonical._normalise(canonical._renumber(canonical._strip(dumped)))
    return json.dumps(view, sort_keys=False, separators=(",", ":"), ensure_ascii=False).encode()


def test_mutation_unsorted_keys_defect_is_caught_and_shrunk_within_sixty_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scenario: A canonicalisation defect is caught."""
    monkeypatch.setattr(canonical, "canonicalize", _unsorted_canonicalize)
    failing: list[dict[str, Any]] = []

    @seed(20261004)
    @settings(max_examples=500, deadline=None, database=None, report_multiple_bugs=False,
              suppress_health_check=list(HealthCheck),
              phases=(Phase.generate, Phase.shrink))  # fmt: skip
    @given(any_rule)
    def prop(doc: dict[str, Any]) -> None:
        try:
            full_chain(doc)
        except HopMismatch:
            failing.append(doc)
            raise

    started = time.monotonic()
    with pytest.raises(HopMismatch):
        prop()
    elapsed = time.monotonic() - started
    minimal = failing[-1]  # Hypothesis replays the shrunk example last
    print(
        f"\n[mutation] caught+shrunk in {elapsed:.1f}s; minimal={json.dumps(minimal, default=str)}"
    )
    assert elapsed < SHRINK_BUDGET_S
    # Minimal: a single action and a leaf (non-boolean) condition survive shrinking.
    assert len(minimal["actions"]) == 1
    assert "children" not in minimal["conditions"]


def test_mutation_sanity_real_canonicalize_passes_the_same_examples() -> None:
    """Control: the same seed passes without the defect, so the failure above is the mutant."""

    @seed(20261004)
    @settings(max_examples=50, deadline=None, database=None)
    @given(any_rule)
    def prop(doc: dict[str, Any]) -> None:
        full_chain(doc)

    prop()
