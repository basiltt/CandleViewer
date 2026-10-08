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


def test_state_root_default_anchors_on_data_dir_not_cwd(tmp_path: Path) -> None:
    s = Settings(parquet_root=str(tmp_path / "data" / "parquet"))
    assert Path(s.bars_state_root) == (tmp_path / "data" / "bars" / "state").resolve()


def test_state_root_must_be_absolute() -> None:
    with pytest.raises(ValueError, match="absolute"):
        Settings(bars_state_root="var/bars")


def test_state_root_symlink_rejected(tmp_path: Path) -> None:
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable on this platform")
    with pytest.raises(ValueError, match="symlink"):
        Settings(bars_state_root=str(link))


async def test_writer_probe_not_deployed_off_and_degraded_when_writer_degraded(
    tmp_path: Path,
) -> None:
    from candleviewer.app import _bars_writer_state
    from candleviewer.health_wiring import register_bars_writer_probe
    from candleviewer.observability.health_probes import (
        BARS_WRITER,
        ComponentState,
        HealthRegistry,
    )

    ctx = build_app_context(_settings(tmp_path, enabled=False))
    runtime = wire_bars(ctx, now_us=lambda: T0, inner_sink=None)
    holder: list[Any] = [None]
    registry = HealthRegistry()
    register_bars_writer_probe(registry, lambda: _bars_writer_state(holder[0]))
    probe = registry._probes[BARS_WRITER]
    assert (await probe.check()).state is ComponentState.NOT_DEPLOYED
    holder[0] = runtime
    assert (await probe.check()).state is ComponentState.HEALTHY
    runtime.writer.degraded = True
    result = await probe.check()
    assert result.state is ComponentState.DEGRADED
    assert "bars_writer_degraded" in result.detail


def test_wire_without_sink_warns_rows_not_persisted(tmp_path: Path) -> None:
    from structlog.testing import capture_logs

    ctx = build_app_context(_settings(tmp_path, enabled=False))
    with capture_logs() as logs:
        wire_bars(ctx, now_us=lambda: T0)
    assert any(e["event"] == "bars_rows_not_persisted" for e in logs)


async def test_tape_narrows_window_when_a_read_returns_too_many_rows() -> None:
    from types import SimpleNamespace

    from candleviewer.bars_wiring import MAX_WINDOW_ROWS, StorageTape
    from candleviewer.storage.models import TimeRange
    from candleviewer.storage.repositories.rows import TradeRow

    widths: list[int] = []

    class Repo:
        async def read_trades(self, sym: str, rng: TimeRange) -> list[TradeRow]:
            w = rng.end_us - rng.start_us
            widths.append(w)
            n = MAX_WINDOW_ROWS + 1 if w > 150_000_000 else 1
            return [
                TradeRow(rng.start_us, sym, "1", "1", "buy", f"{rng.start_us}-{i}")
                for i in range(n)
            ]

    ctx = SimpleNamespace(storage=SimpleNamespace(market_data=Repo()))
    tape = StorageTape(ctx, lambda: T0 + 300_000_000)  # type: ignore[arg-type]
    got = [t async for t in tape.since(SYM, T0)]
    assert widths[0] == 300_000_000 and widths[1] == 150_000_000
    assert got and len(got) < MAX_WINDOW_ROWS


class _FakeTransport:
    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.payloads: list[bytes] = []

    async def connect(self) -> None:
        self.order.append("ilp:connect")

    async def write(self, data: bytes) -> None:
        self.order.append("ilp:write")
        self.payloads.append(data)

    async def close(self) -> None:
        self.order.append("ilp:close")


class _FakePgWire:
    def __init__(self, order: list[str]) -> None:
        self.order = order

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        return [{"n": 0}]

    async def close(self) -> None:
        self.order.append("pg:close")


def test_sink_built_only_on_real_backend(tmp_path: Path) -> None:
    from candleviewer.app import _build_bars_sink
    from candleviewer.storage.questdb.wiring import QuestDbRowSink

    assert _build_bars_sink(_settings(tmp_path, enabled=True)) is None  # fake backend: stub
    real = _settings(tmp_path, enabled=True).model_copy(update={"storage_backend": "real"})
    assert isinstance(_build_bars_sink(real), QuestDbRowSink)  # lazy: no I/O at build


def test_fake_backend_keeps_guarded_stub_and_warning(tmp_path: Path) -> None:
    from structlog.testing import capture_logs

    with capture_logs() as logs:
        app = create_app(_settings(tmp_path, enabled=True))
    assert isinstance(app.state.bars_runtime, BarsRuntime)
    assert any(e["event"] == "bars_rows_not_persisted" for e in logs)


async def test_rows_flow_set_writer_ilp_and_shutdown_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from candleviewer.storage.questdb.wiring import QuestDbRowSink

    order: list[str] = []
    transport = _FakeTransport(order)
    sink = QuestDbRowSink(
        "h:1",
        "h:2",
        "u",
        "p",
        transport=transport,
        pgwire=_FakePgWire(order),  # type: ignore[arg-type]  # structural fake
    )
    ctx = build_app_context(_settings(tmp_path, enabled=False))
    app = FastAPI()
    app.state.app_context = ctx
    now = [T0]
    runtime = wire_bars(ctx, now_us=lambda: now[0], inner_sink=sink, sink_stop=sink.stop)
    app.state.bars_runtime = runtime
    _trace_stop(monkeypatch, runtime.builder_set, "set", order)
    _trace_stop(monkeypatch, runtime.writer, "writer", order)
    async with _lifespan(app):
        await runtime.builder_set.register(M1, SYM, "c1", user="user-1")
        topic = Topic(env="demo", domain="md", symbol=SYM, detail="trade")
        await ctx.bus.bus.publish(topic, trade(T0, seq=1))
        now[0] = T0 + 120_000_000
        await ctx.bus.bus.publish(topic, trade(T0 + 120_000_000, seq=2))
    assert any(b"bars_time" in p for p in transport.payloads)
    marks = [o for o in order if o.startswith(("stop:", "ilp:write", "ilp:close", "pg:close"))]
    # set -> writer drain -> ILP flush -> transport close -> PG-wire close (the trailing
    # `stop:set` is the AppContext's own idempotent bars stop, after the runtime).
    assert marks[:5] == ["stop:set", "stop:writer", "ilp:write", "ilp:close", "pg:close"]
