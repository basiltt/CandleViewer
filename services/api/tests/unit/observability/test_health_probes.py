"""E04-T04 unit tests: aggregation, timeout isolation, edge-triggered events."""

from __future__ import annotations

import asyncio
import itertools

import pytest

from candleviewer.observability.health_probes import (
    CallableProbe,
    ComponentState,
    HealthRegistry,
    NotDeployedProbe,
    ProbeResult,
    SystemEvent,
    worst_of,
)

S = ComponentState


class _Sink:
    def __init__(self) -> None:
        self.events: list[SystemEvent] = []

    async def write(self, event: SystemEvent) -> None:
        self.events.append(event)


def test_rank_order_is_down_warning_degraded_healthy() -> None:
    assert S.DOWN.rank > S.WARNING.rank > S.DEGRADED.rank > S.HEALTHY.rank


@pytest.mark.parametrize("combo", list(itertools.product(list(S), repeat=2)))
def test_worst_of_pairs_is_max_rank(combo: tuple[S, S]) -> None:
    got = worst_of(list(combo))
    assert got.rank == max(c.rank for c in combo)


def test_worst_of_empty_and_not_deployed_is_healthy() -> None:
    assert worst_of([]) is S.HEALTHY
    assert worst_of([S.NOT_DEPLOYED, S.NOT_DEPLOYED]) is S.HEALTHY


async def test_slow_probe_times_out_degraded_others_normal() -> None:
    async def hang() -> ProbeResult:
        await asyncio.sleep(30)
        return ProbeResult(S.HEALTHY)

    async def ok() -> ProbeResult:
        return ProbeResult(S.HEALTHY, "fine")

    reg = HealthRegistry(probe_deadline_s=0.05)
    reg.register(CallableProbe("parquet_store", hang, timeout=10))
    reg.register(CallableProbe("postgres", ok))
    snap = await asyncio.wait_for(reg.refresh(), timeout=2)
    by = {c.name: c for c in snap.components}
    assert by["parquet_store"].state is S.DEGRADED
    assert by["parquet_store"].detail == "probe timeout"
    assert by["postgres"].state is S.HEALTHY
    assert snap.overall is S.DEGRADED


async def test_probe_exception_is_isolated_and_not_leaked() -> None:
    async def boom() -> ProbeResult:
        raise RuntimeError("postgres://user:secret@host/db")

    reg = HealthRegistry()
    reg.register(CallableProbe("postgres", boom))
    reg.register(NotDeployedProbe("oms"))
    snap = await reg.refresh()
    by = {c.name: c for c in snap.components}
    assert by["postgres"].state is S.DOWN
    assert "secret" not in by["postgres"].detail
    assert by["oms"].state is S.NOT_DEPLOYED
    assert snap.overall is S.DOWN


async def test_last_good_at_kept_after_failure() -> None:
    state = {"ok": True}

    async def fn() -> ProbeResult:
        return ProbeResult(S.HEALTHY if state["ok"] else S.DOWN)

    reg = HealthRegistry()
    reg.register(CallableProbe("postgres", fn))
    first = (await reg.refresh()).components[0]
    state["ok"] = False
    second = (await reg.refresh()).components[0]
    assert second.state is S.DOWN
    assert second.last_good_at == first.last_good_at is not None


async def test_transitions_are_edge_triggered() -> None:
    seq = iter([S.HEALTHY, S.HEALTHY, S.DOWN, S.DOWN, S.DOWN, S.HEALTHY])

    async def fn() -> ProbeResult:
        return ProbeResult(next(seq))

    sink = _Sink()
    reg = HealthRegistry(events=sink)
    reg.register(CallableProbe("bybit_public_ws", fn))
    for _ in range(6):
        await reg.refresh()
    assert [e.severity for e in sink.events] == ["error", "info"]
    assert all(e.component == "exchange" for e in sink.events)
    assert "healthy -> down" in sink.events[0].message
    assert sink.events[1].kind == "health_recovered"


async def test_sink_and_publisher_failures_do_not_break_refresh() -> None:
    class Bad:
        async def write(self, event: SystemEvent) -> None:
            raise RuntimeError("x")

    seq = iter([S.HEALTHY, S.DOWN])

    async def fn() -> ProbeResult:
        return ProbeResult(next(seq))

    async def pub(_: object) -> None:
        raise RuntimeError("x")

    reg = HealthRegistry(events=Bad(), on_snapshot=pub)
    reg.register(CallableProbe("postgres", fn))
    await reg.refresh()
    assert (await reg.refresh()).overall is S.DOWN


async def test_observers_and_placeholders_and_ticker() -> None:
    seen: list[str] = []
    reg = HealthRegistry()
    reg.state_observer = lambda n, s: seen.append(n)
    reg.duration_observer = lambda n, d: None
    reg.register_placeholders()
    reg.start(0.01)
    reg.start(0.01)  # idempotent
    for _ in range(100):
        if reg.snapshot() is not None:
            break
        await asyncio.sleep(0.01)
    await reg.stop()
    await reg.stop()
    snap = reg.snapshot()
    assert snap is not None and len(snap.components) == 10
    assert all(c.state is S.NOT_DEPLOYED for c in snap.components)
    assert snap.overall is S.HEALTHY
    assert "disk" in seen
