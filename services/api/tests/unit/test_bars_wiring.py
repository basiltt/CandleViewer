"""`BarBuilderSet` lifespan wiring (E12 #2031): flag, blobs, rows, shutdown order."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI

from candleviewer.app import build_app_context, create_app
from candleviewer.bars.models import BarSpec
from candleviewer.bars_wiring import BarsRuntime, wire_bars
from candleviewer.bus.models import Topic
from candleviewer.main import _lifespan
from candleviewer.settings import Environment, Settings
from tests.unit.bars._trades import SYM, trade, us

M1 = BarSpec(kind="time", interval_ms=60_000)
T0 = us("10:00:00")


class _FakeSink:
    def __init__(self, order: list[str]) -> None:
        self.calls: list[tuple[str, list[dict[str, object]], str]] = []
        self._order = order

    async def write_rows(self, table: str, rows: list[dict[str, object]], ts_us_key: str) -> None:
        self._order.append("rows")
        self.calls.append((table, rows, ts_us_key))


def _trace_stop(mp: pytest.MonkeyPatch, owner: Any, name: str, order: list[str]) -> None:
    real = owner.stop

    async def stop(*args: Any, **kwargs: Any) -> Any:
        order.append(f"stop:{name}")
        return await real(*args, **kwargs)

    mp.setattr(owner, "stop", stop)


def _settings(tmp_path: Path, *, enabled: bool) -> Settings:
    return Settings(
        environment=Environment.DEMO,
        git_sha="deadbeef",
        version="9.9.9",
        bars_enabled=enabled,
        bars_state_root=str(tmp_path / "bars"),
        metrics_enabled=False,
    )


def test_flag_off_by_default_builds_no_runtime(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path, enabled=False))
    assert getattr(app.state, "bars_runtime", None) is None


def test_flag_on_builds_runtime_with_state_root(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path, enabled=True))
    assert isinstance(app.state.bars_runtime, BarsRuntime)


async def test_lifespan_register_publish_shutdown_flushes_blobs_and_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Only the context + runtime: create_app()'s other lifespan tasks need Postgres.
    ctx = build_app_context(_settings(tmp_path, enabled=False))
    app = FastAPI()
    app.state.app_context = ctx
    order: list[str] = []
    sink = _FakeSink(order)
    now = [T0]
    runtime = wire_bars(ctx, now_us=lambda: now[0], inner_sink=sink)
    app.state.bars_runtime = runtime
    _trace_stop(monkeypatch, runtime.builder_set, "set", order)
    _trace_stop(monkeypatch, runtime.writer, "writer", order)

    async with _lifespan(app):
        await runtime.builder_set.register(M1, SYM, "c1", user="user-1")
        topic = Topic(env="demo", domain="md", symbol=SYM, detail="trade")
        await ctx.bus.bus.publish(topic, trade(T0, seq=1))
        now[0] = T0 + 120_000_000
        await ctx.bus.bus.publish(topic, trade(T0 + 120_000_000, seq=2))
    assert order.index("stop:set") < order.index("stop:writer")
    assert list((tmp_path / "bars").rglob("*.state.json"))
    assert sink.calls and sink.calls[0][0] == "bars_time"
    assert "rows" in order and order.index("stop:set") < len(order)
