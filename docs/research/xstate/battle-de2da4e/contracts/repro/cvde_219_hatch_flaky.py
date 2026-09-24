# -*- coding: utf-8 -*-
"""STANDALONE: the #219 escape hatch is context-inherited, so it works or
raises ReentrantWaitError depending on whether the receipt happens to be
done at the task's first await.

CHANGELOG [Unreleased] #219 says: "The receipt can still be handed out
(`asyncio.ensure_future(i.send(..., wait=True))`) and awaited later; only
the in-step await is refused."

`asyncio.ensure_future` copies the CURRENT context, so the task inherits
`_ACTIVE_ACTION_OWNER = <this interpreter>`. The guard in
`Interpreter.send`'s `_Awaitable.__await__` is

    if _ACTIVE_ACTION_OWNER.get() is self and not receipt.done():
        raise ReentrantWaitError(...)

so the hatch succeeds only when the receipt is ALREADY done at the moment
the task first awaits -- a race, not a contract.

Run: python cvde_219_hatch_flaky.py      (needs only stdlib + xstate_statemachine)
"""
from __future__ import annotations
import asyncio, sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.exceptions import ReentrantWaitError

CFG = {
    "id": "hatch",
    "initial": "a",
    "context": {},
    "states": {
        "a": {"on": {"GO": "b"}},
        "b": {"entry": ["handout"], "on": {"LATER": "c"}},
        "c": {},
    },
}


async def trial(slow: bool):
    """slow=True puts one extra awaited step inside the action after the
    hand-out, which is the ONLY difference between the two runs."""
    box = {}

    async def handout(interp, ctx, evt, ad):
        box["fut"] = asyncio.ensure_future(interp.send("LATER", wait=True))
        if slow:
            await asyncio.sleep(0.05)

    m = create_machine(CFG, logic=MachineLogic(actions={"handout": handout}))
    i = Interpreter(m, clock=SimulatedClock())
    await i.start()
    await i.send("GO")
    for _ in range(8):
        await asyncio.sleep(0.02)
    try:
        await asyncio.wait_for(box["fut"], 3)
        out = "resolved"
    except ReentrantWaitError as e:
        out = "ReentrantWaitError"
    except asyncio.TimeoutError:
        out = "TIMEOUT"
    except Exception as e:
        out = repr(e)[:120]
    state = sorted(i.current_state_ids)
    try:
        await asyncio.wait_for(i.stop(), 3)
    except Exception:
        pass
    return out, state


async def main():
    r = {}
    for slow in (False, True):
        outs = set()
        states = []
        for _ in range(5):
            o, s = await trial(slow)
            outs.add(o); states.append(s)
        r["slow=%s" % slow] = (sorted(outs), states[0])
        print("slow=%-5s -> %-40s state=%s" % (slow, sorted(outs), states[0]),
              flush=True)
    a = r["slow=False"][0]
    b = r["slow=True"][0]
    same = a == b
    print()
    if same and a == ["resolved"]:
        print("NOT REPRODUCED: the hatch resolved in both shapes.")
    elif same:
        print("REPRODUCED (always-refused): the documented hatch never "
              "resolves -- %s" % a)
    else:
        print("REPRODUCED (timing-dependent): the documented #219 escape "
              "hatch resolves in one shape and raises in the other -- "
              "no-extra-await=%s, extra-await=%s" % (a, b))
        print("Whether `asyncio.ensure_future(i.send(..., wait=True))` "
              "works depends on whether the receipt is done at the task's "
              "first await, because ensure_future inherits "
              "_ACTIVE_ACTION_OWNER from the action's context.")

asyncio.run(main())
