# -*- coding: utf-8 -*-
"""STANDALONE: rollback + invoke.onDone re-arms the service forever.

B1's shape, minimised: `submitting` invokes `place_order`; its onDone
targets `submitted`, whose entry action `adopt_ack` raises. Under
actionErrorPolicy "rollback" the failed entry unwinds back to
`submitting`, which re-arms `place_order` -- a real exchange order per
lap. Run with CV=async (async def service) and CV=def (plain def).
stdlib + xstate_statemachine only.
"""
import asyncio, os, sys
from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock

STYLE = os.environ.get("CV", "async")
MAXIT = os.environ.get("MAXIT")  # e.g. "25"

CFG = {
    "id": "order", "initial": "submitting",
    "actionErrorPolicy": "rollback", "onUnhandled": "defer",
    "guardErrorPolicy": "raise", "strictTargets": True, "strict": True,
    "context": {},
    "states": {
        "submitting": {"invoke": {
            "id": "po", "src": "place_order",
            "onDone": {"target": "#order.submitted"},
            "onError": {"target": "#order.unknown"}}},
        "submitted": {"entry": ["adopt_ack"]},
        "unknown": {"type": "final"},
    },
}
if MAXIT:
    CFG["maxIterations"] = int(MAXIT)

CALLS = []


def adopt_ack(i, c, e, a):
    raise RuntimeError("boom:adopt_ack")


def svc_def(i, c, e):
    CALLS.append(1)
    return {"ok": True}


async def svc_async(i, c, e):
    CALLS.append(1)
    return {"ok": True}


async def main():
    logic = MachineLogic(
        actions={"adopt_ack": adopt_ack},
        services={"place_order": svc_def if STYLE == "def" else svc_async},
        strict=True)
    m = create_machine(CFG, logic=logic, strict_targets=True)
    i = Interpreter(m, clock=SimulatedClock())
    await i.start()
    try:
        await asyncio.wait_for(asyncio.sleep(5.0), 6.0)
    except asyncio.TimeoutError:
        pass
    n = len(CALLS)
    print("style=%s maxIterations=%s place_order_calls=%d states=%s "
          "status=%s error=%r" % (STYLE, MAXIT, n, sorted(i.current_state_ids),
                                  i.status, i.error))
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception as e:
        print("stop:", repr(e))
    # A real exchange order per lap is the defect; 1 is the safe answer.
    sys.exit(1 if n > 1 else 0)


asyncio.run(main())
