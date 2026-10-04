"""E35-S02-B1 (#1809): create_app() runs the evaluator behind `rules_evaluator_enabled`."""

from __future__ import annotations

import asyncio
import json
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

from candleviewer.app import create_app
from candleviewer.rules.ir.models import MetricRef
from candleviewer.rules.manager import Actor, InMemoryRuleStore
from candleviewer.rules.runner import EvalTick, RuleEvaluationRunner
from candleviewer.settings import Settings

FIX = Path(__file__).parents[1] / "fixtures/rule_ir"
OWNER = Actor("u1", "s1", frozenset({"rules:arm_live"}), is_owner=True, step_up_fresh=True)


def _ir() -> dict[str, Any]:
    raw = json.loads((FIX / "form_simple_0.json").read_text(encoding="utf-8"))
    raw["conditions"]["right"]["const"] = 100
    raw["actions"][0]["params"] = {"channel": "ui", "severity": "info", "template": "x"}
    return raw  # type: ignore[no-any-return]


async def test_evaluator_not_constructed_when_flag_off() -> None:
    ctx = create_app().state.app_context
    ctx.rules.bind(store=InMemoryRuleStore())
    await ctx.rules.start(ctx)
    try:
        assert ctx.rules.runner is None
    finally:
        await ctx.rules.stop(1.0)


async def test_create_rule_feed_snapshot_evaluator_records_result() -> None:
    """create rule -> simulate -> feed snapshot -> evaluator runs -> result recorded."""
    ctx = create_app(Settings(rules_evaluator_enabled=True)).state.app_context
    ctx.rules.bind(store=InMemoryRuleStore())
    await ctx.rules.start(ctx)
    try:
        runner = ctx.rules.runner
        assert isinstance(runner, RuleEvaluationRunner)
        mgr = ctx.rules.manager()
        assert mgr is not None
        created = await mgr.create(_ir(), OWNER)
        rid = created["id"]
        await mgr.set_mode(rid, "simulate", OWNER, "k-sim")
        ref = MetricRef.model_validate({"metric": "price", "params": {"n": 14}})
        src = ctx.rules.metric_source
        assert src is not None
        src.push(ref, Decimal("150"), time.time_ns() // 1_000_000)
        await runner.process(EvalTick("on_price_update", "BTCUSDT"))
        await asyncio.sleep(0)
        print({k: (e.stats, e.rule.trigger.type) for k, e in runner._evaluators.items()})
        await asyncio.gather(*list(ctx.rules._tasks))
        row = await mgr._s.get(rid)
        assert row is not None and row.simulation_fires == 1
    finally:
        await ctx.rules.stop(1.0)


async def test_unpushed_metric_skips_stale_never_fires() -> None:
    ctx = create_app(Settings(rules_evaluator_enabled=True)).state.app_context
    ctx.rules.bind(store=InMemoryRuleStore())
    await ctx.rules.start(ctx)
    try:
        mgr = ctx.rules.manager()
        assert mgr is not None and ctx.rules.runner is not None
        rid = (await mgr.create(_ir(), OWNER))["id"]
        await mgr.set_mode(rid, "simulate", OWNER, "k-sim")
        await ctx.rules.runner.process(EvalTick("on_price_update", "BTCUSDT"))
        row = await mgr._s.get(rid)
        assert row is not None and row.simulation_fires == 0
    finally:
        await ctx.rules.stop(1.0)


async def test_queue_is_bounded_and_drops_oldest() -> None:
    async def _none() -> list[Any]:
        return []

    from candleviewer.rules.evaluator import SnapshotBuilder
    from candleviewer.rules.runner import QUEUE_BOUND, PushedMetricSource

    r = RuleEvaluationRunner(_none, SnapshotBuilder(PushedMetricSource()), lambda *_: None, print)  # type: ignore[arg-type]
    for _ in range(QUEUE_BOUND + 5):
        r.submit(EvalTick("on_price_update"))
    assert r.dropped == 5
