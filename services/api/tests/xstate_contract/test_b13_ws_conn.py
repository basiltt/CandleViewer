"""B13 `ws_conn` transitions through the factory with a fake runtime (E08-T04)."""

from __future__ import annotations

import pytest
from xstate_statemachine import SimulatedClock

from candleviewer.statechart import build
from candleviewer.statechart.bindings import b13_ws_conn as b13


class _Rt:
    attempt = 0

    def __init__(self, *, fail_open: bool = False, budget: bool = False) -> None:
        self.fail_open, self.budget = fail_open, budget
        self.health: list[str] = []

    def is_private(self) -> bool:
        return False

    def budget_exhausted(self) -> bool:
        return self.budget

    async def open_socket(self) -> None:
        if self.fail_open:
            raise OSError("dial")

    async def authenticate(self) -> None: ...
    async def subscribe(self) -> None: ...
    async def close_socket(self) -> None: ...
    async def teardown_session(self) -> None: ...
    def start_session(self, interp: object) -> None: ...
    def schedule_backoff(self, interp: object) -> None: ...
    def schedule_budget_recheck(self, interp: object) -> None: ...

    async def emit_health(self, state: str) -> None:
        self.health.append(state)

    def reset_attempt(self) -> None: ...
    def bump_attempt(self) -> None: ...


async def _drive(rt: _Rt, key: str, *events: str) -> tuple[set[str], list[str]]:
    b13.register_runtime(key, rt)
    try:
        r = await build("ws_conn", ctx={"conn_key": key}, clock=SimulatedClock(), lane="platform")
        for ev in events:
            await r.interpreter.send(ev, wait=True)
        for _ in range(50):
            await __import__("asyncio").sleep(0)
        ids = {s.rsplit(".", 1)[-1] for s in r.interpreter.current_state_ids}
        await r.interpreter.stop()
        return ids, rt.health
    finally:
        b13.unregister_runtime(key)


async def test_connect_reaches_live_and_emits_healthy() -> None:
    ids, health = await _drive(_Rt(), "t1", "CONNECT")
    assert "live" in ids and health == ["healthy"]


async def test_dial_failure_backs_off_and_emits_degraded() -> None:
    ids, health = await _drive(_Rt(fail_open=True), "t2", "CONNECT")
    assert "backing_off" in ids and health == ["degraded"]


async def test_budget_exhausted_blocks() -> None:
    ids, _ = await _drive(_Rt(budget=True), "t3", "CONNECT")
    assert "budget_blocked" in ids


async def test_live_socket_closed_then_backoff_due_reconnects() -> None:
    ids, health = await _drive(_Rt(), "t4", "CONNECT", "SOCKET_CLOSED", "BACKOFF_DUE")
    assert "live" in ids and health == ["healthy", "degraded", "healthy"]


@pytest.mark.parametrize("ev", ["SHUTDOWN", "KILL"])
async def test_shutdown_and_kill_terminate(ev: str) -> None:
    ids, _ = await _drive(_Rt(), f"t5{ev}", "CONNECT", ev)
    assert "closed" in ids
