# -*- coding: utf-8 -*-
"""Verify #204 on main @ 19cb1f1: statesToInvoke discipline (SCXML 6.1).

A `def`/`async def` service armed by a transition that an `always` rolls
forward, or that a rollback undoes, must never be submitted -- on EITHER
engine. Matrix: {def, async def} x {Interpreter, SyncInterpreter} x
{roll-forward, rollback}. SyncInterpreter has no async-def lane -> 6 cells.
Anti-regression: invoke still runs when settle does not exit the state,
and when there is no always at all.

Exit 0 only if every cell passes.
"""
from __future__ import annotations

import asyncio
import json

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    OverflowPolicy,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.clock import SimulatedClock

CALLS: list = []
FAILS: list = []


def fail(label, detail):
    FAILS.append((label, detail))
    print("FAIL:", label, "--", detail)


def chart(case: str, has_always: bool = True) -> dict:
    sub = {
        "entry": ["bump"],
        "invoke": {
            "id": "kid",
            "src": "submit_child",
            "onDone": {"target": "#m.armed"},
            "onError": {"target": "#m.armed"},
        },
    }
    if case == "A" and has_always:
        sub["always"] = [{"target": "#m.armed", "guard": "roll_forward"}]
    return {
        "id": "m",
        "initial": "armed",
        "actionErrorPolicy": "rollback",
        "onUnhandled": "defer",
        "guardErrorPolicy": "raise",
        "strictTargets": True,
        "strict": True,
        "context": {"n": 0},
        "states": {
            "armed": {"on": {"GO": {"target": "#m.submitting"}}},
            "submitting": sub,
        },
    }


def logic(case: str, style: str, guard_value: bool = True) -> MachineLogic:
    def bump(i, ctx, e, ad):  # noqa: ANN001
        if case == "B":
            raise RuntimeError("entry action failed")
        ctx["n"] = ctx.get("n", 0) + 1

    def svc_def(i, ctx, e):  # noqa: ANN001
        CALLS.append("submit_child")
        return {"ok": True}

    async def svc_async(i, ctx, e):  # noqa: ANN001
        CALLS.append("submit_child")
        return {"ok": True}

    return MachineLogic(
        actions={"bump": bump},
        guards={"roll_forward": lambda ctx, e: guard_value},
        services={"submit_child": svc_def if style == "def" else svc_async},
        strict=True,
    )


async def run_async(case: str, style: str, has_always: bool = True, guard_value: bool = True):
    CALLS.clear()
    m = create_machine(
        chart(case, has_always), logic=logic(case, style, guard_value)
    )
    i = Interpreter(
        m, clock=SimulatedClock(), max_queue_size=64,
        overflow_policy=OverflowPolicy.RAISE,
    )
    await i.start()
    await asyncio.sleep(0.05)
    try:
        await asyncio.wait_for(i.send("GO", wait=True), 5)
    except Exception:  # noqa: BLE001
        pass
    for _ in range(6):
        await asyncio.sleep(0.03)
    states, calls = sorted(i.current_state_ids), list(CALLS)
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception:  # noqa: BLE001
        pass
    return states, calls


def run_sync(case: str, style: str = "def", has_always: bool = True, guard_value: bool = True):
    CALLS.clear()
    m = create_machine(
        chart(case, has_always), logic=logic(case, style, guard_value)
    )
    i = SyncInterpreter(m, clock=SimulatedClock())
    i.start()
    try:
        i.send("GO")
    except Exception:  # noqa: BLE001
        pass
    states, calls = sorted(i.current_state_ids), list(CALLS)
    try:
        i.stop()
    except Exception:  # noqa: BLE001
        pass
    return states, calls


async def main() -> int:
    print("== Roll-forward / rollback leak matrix ==")
    # (case, style, engine) -> (states, calls)
    lanes = [
        ("A", "async", "async"),
        ("A", "def", "async"),
        ("A", "def", "sync"),
        ("B", "async", "async"),
        ("B", "def", "async"),
        ("B", "def", "sync"),
    ]
    results = {}
    for case, style, engine in lanes:
        if engine == "async":
            states, calls = await run_async(case, style)
        else:
            states, calls = run_sync(case, style)
        results[(case, style, engine)] = (states, calls)
        leaked = bool(calls)
        print(f"  case={case} style={style:5} engine={engine:5} states={states} calls={calls} leaked={leaked}")
        if leaked:
            fail(f"204-{case}-{style}-{engine}", f"service leaked: {calls}")
    if not FAILS:
        print("ok  : no lane leaked the service call")

    print("== Anti-regression: invoke runs when always guard is False ==")
    for style, engine in (("async", "async"), ("def", "async"), ("def", "sync")):
        if engine == "async":
            states, calls = await run_async("A", style, has_always=True, guard_value=False)
        else:
            states, calls = run_sync("A", style, has_always=True, guard_value=False)
        print(f"  style={style:5} engine={engine:5} states={states} calls={calls}")
        if calls != ["submit_child"]:
            fail(f"204-regress-guardfalse-{style}-{engine}", f"states={states} calls={calls}")

    print("== Anti-regression: invoke runs when no always present ==")
    for style, engine in (("async", "async"), ("def", "async"), ("def", "sync")):
        if engine == "async":
            states, calls = await run_async("A", style, has_always=False)
        else:
            states, calls = run_sync("A", style, has_always=False)
        print(f"  style={style:5} engine={engine:5} states={states} calls={calls}")
        if calls != ["submit_child"]:
            fail(f"204-regress-noalways-{style}-{engine}", f"states={states} calls={calls}")

    print()
    if FAILS:
        print(f"VERDICT: FAIL ({len(FAILS)} cell(s))")
        for label, detail in FAILS:
            print("  -", label, ":", detail)
        return 1
    print("VERDICT: ALL CELLS PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
