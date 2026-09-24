# -*- coding: utf-8 -*-
"""STANDALONE: is `last_error` still visible after a chain trip, and does
its visibility depend on the service kind?

Same B18 shape as r4. The chain trips (SPIN shed as chain_budget) while
the kill switch runs a service. We sample last_error right after the trip
and again after the service completes. CV=async|def.
"""
import asyncio, os, sys
from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock

STYLE = os.environ.get("CV", "async")
CFG = {
    "id": "ks", "type": "parallel", "maxIterations": 5,
    "actionErrorPolicy": "rollback", "onUnhandled": "error",
    "guardErrorPolicy": "raise", "strictTargets": True, "strict": True,
    "context": {"ext": 0},
    "states": {
        "noise": {"initial": "a", "states": {"a": {"on": {
            "SPIN": {"actions": [{"type": "raise",
                                  "params": {"event": "SPIN"}}]}}}}},
        "switch": {"initial": "clear", "states": {
            "clear": {"on": {"ENGAGE": {"target": "#ks.switch.cancelling"}}},
            "cancelling": {"on": {"ENGAGE": {}}, "invoke": {
                "id": "cx", "src": "svc",
                "onDone": {"target": "#ks.switch.engaged"},
                "onError": {"target": "#ks.switch.engaged"}}},
            "engaged": {"on": {"ENGAGE": {}}}}},
    },
}


def sd(i, c, e):
    return {"ok": True}


async def sa(i, c, e):
    await asyncio.sleep(0.05)
    return {"ok": True}


async def main():
    logic = MachineLogic(services={"svc": sd if STYLE == "def" else sa},
                         strict=True)
    i = Interpreter(create_machine(CFG, logic=logic, strict_targets=True),
                    clock=SimulatedClock())
    await i.start()
    await i.send("SPIN")
    r = await i.send("ENGAGE", priority=True, wait=True)
    at_step = type(getattr(r, "error", None)).__name__
    just_after = type(i.last_error).__name__
    await asyncio.sleep(0.5)
    settled = type(i.last_error).__name__
    print("style=%s receipt.error=%s last_error_after_step=%s "
          "last_error_settled=%s states=%s"
          % (STYLE, at_step, just_after, settled, sorted(i.current_state_ids)))
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception as e:
        print("stop:", repr(e))
    # The trip must be observable on the step it affects.
    sys.exit(0 if "RunawayChainError" in (at_step, just_after) else 1)


asyncio.run(main())
