"""Correct-usage variant: NO action hook. Root quiescent; a separate coroutine
(the documented 'settled interpreter' caller) snapshots the root while the
child actor is mid-entry (its async entry action awaits)."""
from __future__ import annotations
import asyncio, logging
from xstate_statemachine import Interpreter, MachineLogic, create_machine
logging.disable(logging.CRITICAL)

PARENT = {"id":"par","initial":"run","states":{"run":{"invoke":{"src":"child","id":"kid"}}}}
CHILD = {"id":"kid","initial":"x","context":{"q":0,"p":0},
         "states":{"x":{"on":{"STEP":"y"}},"y":{"entry":["set_q","set_p"]}}}

async def set_q(i_, ctx, e, am):
    ctx["q"] = 100
    await asyncio.sleep(0.05)   # yields the loop mid-entry
async def set_p(i_, ctx, e, am):
    ctx["p"] = 101

async def amain():
    root = await Interpreter(create_machine(PARENT, logic=MachineLogic(
        services={"child": create_machine(CHILD, logic=MachineLogic(
            actions={"set_q": set_q, "set_p": set_p}))}))).start()
    kid = next(a for k,a in root._actors.items() if k.endswith("kid"))
    task = kid.send("STEP", wait=True)
    await asyncio.sleep(0.02)   # child now mid-entry, between set_q and set_p
    print("root in flight :", root._step_in_flight())
    print("kid  in flight :", kid._step_in_flight())
    try:
        blob = root.get_persisted_snapshot()
        sub = list((blob.get("actors") or {}).values())[0]["snapshot"]
        ctx = sub["context"]
        torn = (ctx["q"] > 0) != (ctx["p"] > 0)
        print("ACCEPTED", sub["state_ids"], ctx, ">>> TORN" if torn else "")
    except Exception as exc:
        print("REFUSED", type(exc).__name__)
    await task
    print("settled ctx    :", dict(kid.context), sorted(kid.current_state_ids))
    await root.stop()

asyncio.run(amain())
