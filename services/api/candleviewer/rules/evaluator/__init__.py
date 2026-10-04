"""Deterministic rule evaluator (M15, E35-S02; 24-internal-schemas.md 11.5 E1-E10).

Plain code, permanently excluded from the statechart catalogue (29-statechart-adoption-plan
section 3; BENCH-2). It only *decides*; action execution is E35-S03. The IR is data, never code
(ADR-0007 R1): no eval/exec/compile anywhere in this package.
"""

from __future__ import annotations

from candleviewer.rules.evaluator.engine import EvaluationResult, Evaluator, EvaluatorStats
from candleviewer.rules.evaluator.nodes import NodeTrace
from candleviewer.rules.evaluator.snapshot import (
    MetricSnapshot,
    MetricSource,
    MetricValue,
    SnapshotBuilder,
    metric_key,
)

__all__ = [
    "EvaluationResult",
    "Evaluator",
    "EvaluatorStats",
    "MetricSnapshot",
    "MetricSource",
    "MetricValue",
    "NodeTrace",
    "SnapshotBuilder",
    "metric_key",
]
