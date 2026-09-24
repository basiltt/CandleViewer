# -*- coding: utf-8 -*-
"""LD-01 (residual) @ f28719c -- STANDALONE (stdlib + xstate_statemachine).

A plain `def` service is still CALLED when an `always` transition rolls the
machine forward out of the invoking state before the invoke should ever run.

#193 moved the def-service executor handoff into the engine-held task so
that rollback AND roll-forward cancel before submission. The ROLLBACK half
is fixed (case B passes on the async engine). The ROLL-FORWARD half is NOT:
with `always` leaving the state, the plain callable is still submitted.

`SyncInterpreter` fails BOTH halves.

Chart (no catalogue dependency):

    armed --GO--> submitting
    submitting: entry [bump], invoke submit_child,
                always -> armed   (case A, guard true)

In an OMS `submit_child` places a live child order. A roll-forward exists
precisely to say "this slice is below minimum, do not send it".

Exit 0 = every lane clean. Exit 1 = at least one leak (the finding).
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

CALLS: list[str] = []
ROWS: list[dict] = []


def chart(case: str) -> dict:
    sub = {
        "entry": ["bump"],
        "invoke": {
            "id": "kid",
            "src": "submit_child",
            "onDone": {"target": "#m.armed"},
            "onError": {"target": "#m.armed"},
        },
    }
    if case == "A":
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


def logic(case: str, style: str) -> MachineLogic:
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
        guards={"roll_forward": lambda ctx, e: True},
        services={"submit_child": svc_def if style == "def" else svc_async},
        strict=True,
    )


def record(case: str, style: str, engine: str, states, ctx) -> None:
    leaked = bool(CALLS)
    ROWS.append(
        {
            "case": case,
            "style": style,
            "engine": engine,
            "states": sorted(states),
            "context": dict(ctx),
            "service_calls": list(CALLS),
            "leaked": leaked,
        }
    )
    print(
        ("LEAK " if leaked else "ok   ")
        + "case %s | %-5s service | %-5s engine | states=%s ctx=%s calls=%s"
        % (case, style, engine, sorted(states), dict(ctx), CALLS),
        flush=True,
    )


async def run_async(case: str, style: str) -> None:
    CALLS.clear()
    m = create_machine(chart(case), logic=logic(case, style))
    i = Interpreter(
        m,
        clock=SimulatedClock(),
        max_queue_size=64,
        overflow_policy=OverflowPolicy.RAISE,
    )
    await i.start()
    await asyncio.sleep(0.05)
    try:
        await asyncio.wait_for(i.send("GO", wait=True), 5)
    except Exception as exc:  # noqa: BLE001
        print("   send raised:", repr(exc), flush=True)
    for _ in range(6):
        await asyncio.sleep(0.03)
    record(case, style, "async", i.current_state_ids, i.context)
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception:  # noqa: BLE001
        pass


def run_sync(case: str) -> None:
    CALLS.clear()
    m = create_machine(chart(case), logic=logic(case, "def"))
    i = SyncInterpreter(m, clock=SimulatedClock())
    i.start()
    try:
        i.send("GO")
    except Exception as exc:  # noqa: BLE001
        print("   send raised:", repr(exc), flush=True)
    record(case, "def", "sync", i.current_state_ids, i.context)
    try:
        i.stop()
    except Exception:  # noqa: BLE001
        pass


async def main() -> int:
    for case in ("A", "B"):
        for style in ("async", "def"):
            await run_async(case, style)
        run_sync(case)
    leaks = [r for r in ROWS if r["leaked"]]
    print("\n%d/%d lanes leaked the service call" % (len(leaks), len(ROWS)))
    for r in leaks:
        print("  LEAK: case %s / %s service / %s engine"
              % (r["case"], r["style"], r["engine"]))
    print(json.dumps(ROWS, indent=1))
    return 1 if leaks else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
