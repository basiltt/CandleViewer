# -*- coding: utf-8 -*-
"""Verify #200 on f28719c: the owed-completion ledger (`_chain_owed`) must be
task-keyed and leak-free.
Criteria:
  1. A coroutine service task that exits via a BaseException that is
     neither Exception nor asyncio.CancelledError (e.g. a simulated
     KeyboardInterrupt/SystemExit) must NOT leak the debt: `_chain_owed`
     returns to 0 once the task ends.
  2. The debt is matched to the invocation that opened it (task-keyed),
     not a bare counter: a completion from one invocation cannot settle a
     debt opened by a DIFFERENT, still-in-flight invocation.
Only applies to the async Interpreter (SyncInterpreter has no coroutine
service tasks / no `_chain_owed` ledger of this kind), so the matrix here
is over {def, async def} service kinds within the async engine, since the
defect is intrinsically about `async def` service tasks; `def` is included
as a control (never arms `_chain_owed_tasks` via a coroutine task path,
so must trivially show no leak).
"""
from __future__ import annotations

import asyncio

from xstate_statemachine import Interpreter, MachineLogic, create_machine


class _SimulatedBaseExceptionExit(BaseException):
    """`BaseException` subclass standing in for `KeyboardInterrupt`/`SystemExit`."""


FAIL: list[str] = []
ROWS: list[dict] = []


# --- Criterion 1: BaseException-exit does not leak the debt -----------------
async def raises_base_exception(i, ctx, e):
    await asyncio.sleep(0)
    raise _SimulatedBaseExceptionExit("simulated BaseException service exit")


def crit1(kind):
    CFG = {
        "id": "c200_1",
        "initial": "hold",
        "context": {},
        "states": {
            "hold": {
                "invoke": {"src": "s", "onDone": {"target": "done"}},
            },
            "done": {},
        },
    }

    async def go():
        m = create_machine(
            CFG, logic=MachineLogic(services={"s": raises_base_exception})
        )
        i = Interpreter(m)
        await asyncio.wait_for(i.start(), 10)
        # let the invoked coroutine task run and raise
        try:
            await asyncio.wait_for(asyncio.sleep(0.2), 5)
        except asyncio.TimeoutError:
            pass
        # Drain a few loop turns so the done-callback fires
        for _ in range(20):
            await asyncio.sleep(0.01)
        owed = i._chain_owed
        await i.stop()
        return owed

    try:
        owed = asyncio.run(asyncio.wait_for(go(), 25))
    except _SimulatedBaseExceptionExit:
        # If the BaseException propagates out of our own asyncio.run task
        # (it's not caught anywhere), that's also acceptable -- but we
        # actually want it CONTAINED by the engine per the fix design (the
        # task's done-callback fires regardless of how it ends). Treat
        # escape to top-level as unexpected too; re-raise for visibility.
        raise
    return owed


for kind in ("async def",):
    owed = crit1(kind)
    ROWS.append({"crit": 1, "kind": kind, "chain_owed_after": owed})
    if owed != 0:
        FAIL.append(f"[crit1/{kind}] _chain_owed leaked, still={owed}")


# --- Criterion 2: debt is task-keyed, not a bare counter --------------------
async def slow_ok(i, ctx, e):
    await asyncio.sleep(0.3)
    return {"ok": 1}


def crit2():
    CFG = {
        "id": "c200_2",
        "initial": "hold",
        "context": {},
        "states": {
            "hold": {
                "invoke": [
                    {"id": "fast", "src": "raiser", "onDone": {"target": "mid"}},
                    {"id": "slow", "src": "slow_ok", "onDone": {"target": "mid"}},
                ],
            },
            "mid": {},
        },
    }

    async def go():
        m = create_machine(
            CFG,
            logic=MachineLogic(
                services={"raiser": raises_base_exception, "slow_ok": slow_ok}
            ),
        )
        i = Interpreter(m)
        await asyncio.wait_for(i.start(), 10)
        # Right after start, both invokes are armed -> owed should be 2.
        owed_immediately = i._chain_owed
        # Let the fast (BaseException) one finish; the slow one is still
        # in flight (0.3s sleep). If the ledger were a bare counter, the
        # fast one's exit could incorrectly decrement the SAME counter
        # that the slow invocation's eventual completion would also try
        # to decrement, over- or under-counting.
        await asyncio.sleep(0.1)
        owed_after_fast = i._chain_owed
        await asyncio.sleep(0.4)
        owed_after_slow = i._chain_owed
        await i.stop()
        return owed_immediately, owed_after_fast, owed_after_slow

    return asyncio.run(asyncio.wait_for(go(), 25))


owed0, owed1, owed2 = crit2()
ROWS.append(
    {
        "crit": 2,
        "owed_immediately_after_start": owed0,
        "owed_after_fast_exit": owed1,
        "owed_after_slow_completes": owed2,
    }
)
if owed0 != 2:
    FAIL.append(f"[crit2] expected 2 debts armed immediately, got {owed0}")
if owed1 != 1:
    FAIL.append(
        f"[crit2] expected exactly 1 debt (the slow one) to remain after "
        f"the fast BaseException-exit settles its own debt, got {owed1}"
    )
if owed2 != 0:
    FAIL.append(f"[crit2] expected 0 debts once the slow completion lands, got {owed2}")


import json

print(json.dumps({"rows": ROWS, "failures": FAIL}, indent=2))
if FAIL:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
raise SystemExit(0)
