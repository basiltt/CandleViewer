"""E12-T04 determinism harness: BI-1..BI-6 over all six builders (fast PR-gate subset).

The full 1M-trade x standard-matrix run is `bench.bar_determinism.run`, nightly
(`.github/workflows/bar-determinism-nightly.yml`). Here: a seeded 100k-trade tape for one spec
per builder kind (one test per spec, so a violation names the spec), plus small adversarial
seeds for the whole matrix. Every failure message is the harness report: invariant, builder,
spec, first offending bar and the seed.
"""

from __future__ import annotations

import ast
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest

from bench.bar_determinism import generator, invariants
from bench.bar_determinism.generator import GenConfig
from candleviewer.exchange.base.models import TradeEvent

PR_GATE_N = 100_000
PR_GATE_SEED = 12004
_TAPES: dict[tuple[int, int], list[TradeEvent]] = {}


def tape(seed: int, n: int, **kw: Any) -> list[TradeEvent]:
    key = (seed, n)
    if kw:
        return generator.generate(GenConfig(seed=seed, n=n, **kw))
    if key not in _TAPES:
        _TAPES[key] = generator.generate(GenConfig(seed=seed, n=n))
    return _TAPES[key]


#: PR gate: one spec per builder kind on the 100k tape (budget: a few minutes under coverage);
#: the whole matrix runs on the adversarial tapes below and at 1M trades nightly.
PR_GATE_SPECS = ["time:1m", "tick:100", "volume:0.25", "range:20", "delta:2", "renko:10"]


@pytest.mark.parametrize("label", PR_GATE_SPECS)
def test_bi_invariants_hold_on_pr_gate_tape(label: str) -> None:
    spec = invariants.STANDARD_SPECS[label]
    v = invariants.check(label, spec, tape(PR_GATE_SEED, PR_GATE_N), seed=PR_GATE_SEED)
    assert not v, invariants.report(v)


ADVERSARIAL: dict[str, dict[str, Any]] = {
    "huge_prints": {"p_huge": 0.05, "threshold_lots": 5_000},
    "exact_hits": {"p_exact": 0.2, "threshold_lots": 250},
    "reversals": {"p_reversal": 0.05, "jump_ticks": 25},
    "silences_and_late": {"p_silence": 0.02, "p_late": 0.1},
    "duplicates_pareto_skew": {"p_duplicate": 0.05, "size_dist": "pareto", "buy_skew": 0.3},
}


@pytest.mark.parametrize("pattern", list(ADVERSARIAL))
@pytest.mark.parametrize("label", list(invariants.STANDARD_SPECS))
def test_bi_invariants_hold_on_adversarial_tapes(label: str, pattern: str) -> None:
    seed = 500 + list(ADVERSARIAL).index(pattern)
    t = tape(seed, 3_000, **ADVERSARIAL[pattern])
    v = invariants.check(label, invariants.STANDARD_SPECS[label], t, seed=seed, cuts=5)
    assert not v, invariants.report(v)


def test_generator_same_seed_same_tape_different_seed_different_tape() -> None:
    a, b = (
        generator.generate(GenConfig(seed=1, n=500)),
        generator.generate(GenConfig(seed=1, n=500)),
    )
    assert [t.model_dump() for t in a] == [t.model_dump() for t in b]
    c = generator.generate(GenConfig(seed=2, n=500))
    assert [t.price for t in a] != [t.price for t in c]


def test_generator_emits_every_adversarial_pattern() -> None:
    cfg = GenConfig(
        seed=3,
        n=20_000,
        p_huge=0.01,
        p_exact=0.01,
        p_reversal=0.01,
        p_silence=0.01,
        p_late=0.01,
        p_duplicate=0.01,
    )
    t = generator.generate(cfg)
    ids = [x.trade_id for x in t]
    assert len(ids) != len(set(ids))  # duplicate trade ids
    assert any(x.qty >= cfg.threshold_lots * 2 * generator.LOT for x in t)  # N-threshold prints
    assert any(x.qty == cfg.threshold_lots * generator.LOT for x in t)  # exact threshold
    assert any(x.ts_event % cfg.boundary_us == 0 for x in t)  # exact boundary
    gaps = [b.ts_event - a.ts_event for a, b in pairwise(t)]
    assert max(gaps) >= 2 * cfg.boundary_us  # silences
    assert min(gaps) < 0  # late arrivals
    assert any(
        abs(b.price - a.price) >= cfg.jump_ticks * generator.TICK for a, b in pairwise(t)
    )  # rapid reversals


def test_generator_is_offline_by_construction() -> None:
    src = Path(generator.__file__).read_text(encoding="utf-8")
    mods = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module.split(".")[0])
    assert mods <= {
        "__future__",
        "random",
        "uuid",
        "collections",
        "dataclasses",
        "decimal",
        "candleviewer",
    }
    assert "exchange.base.models" in src and "open(" not in src


def test_pr_gate_covers_every_builder_kind() -> None:
    kinds = {invariants.STANDARD_SPECS[s].kind for s in PR_GATE_SPECS}
    assert kinds == {"time", "tick", "volume", "range", "delta", "renko"}


def test_violation_report_names_invariant_builder_spec_bar_and_seed() -> None:
    v = invariants.Violation("BI-3", "delta", "delta:2", 41, 12004, "x")
    assert str(v) == "BI-3 violated: builder=delta spec=delta:2 first_bar=41 seed=12004: x"


def test_throughput_gate_warns_over_10_and_fails_over_25_percent() -> None:
    from bench.bar_determinism import run

    warns, fails = run.compare(
        {"a": 95.0, "b": 85.0, "c": 70.0, "d": 1.0}, {"a": 100.0, "b": 100.0, "c": 100.0}
    )
    assert [w.split(":")[0] for w in warns] == ["b"]
    assert [f.split(":")[0] for f in fails] == ["c"]  # "d" has no baseline: reported only


def test_throughput_baseline_is_never_rewritten_by_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    from bench.bar_determinism import run

    monkeypatch.setenv("CI", "true")
    before = run.BASELINE.read_bytes()
    assert run.main(["--n", "200", "--repeats", "1", "--skip-invariants", "--update-baseline"]) == 2
    assert run.BASELINE.read_bytes() == before
