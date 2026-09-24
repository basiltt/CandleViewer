# -*- coding: utf-8 -*-
"""STANDALONE: does the rollback+onDone cycle report a chain trip?

Same machine as r1 with a plugin recording every error hook and the
action-error hook, so we can see whether the engine surfaces
RunawayChainError (CHANGELOG #201 claims both async lanes trip) or
silently spins. CV=async|def, MAXIT optional.
"""
import asyncio, os, sys
from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.plugins import PluginBase

STYLE = os.environ.get("CV", "async")
MAXIT = os.environ.get("MAXIT")
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


class P(PluginBase):
    def __init__(self):
        self.errors = []
        self.dropped = []
        self.action_errors = 0

    def on_error(self, i, e):
        self.errors.append(repr(e))

    def on_action_error(self, i, a, e):
        self.action_errors += 1

    def on_event_dropped(self, i, e, reason):
        self.dropped.append((getattr(e, "type", "?"), reason))


def adopt_ack(i, c, e, a):
    raise RuntimeError("boom:adopt_ack")


def svc_def(i, c, e):
    CALLS.append(1); return {"ok": True}


async def svc_async(i, c, e):
    CALLS.append(1); return {"ok": True}


async def main():
    logic = MachineLogic(actions={"adopt_ack": adopt_ack},
                         services={"place_order":
                                   svc_def if STYLE == "def" else svc_async},
                         strict=True)
    i = Interpreter(create_machine(CFG, logic=logic, strict_targets=True),
                    clock=SimulatedClock())
    p = P(); i.use(p)
    await i.start()
    await asyncio.sleep(3.0)
    print("style=%s maxIt=%s calls=%d states=%s status=%s i.error=%r"
          % (STYLE, MAXIT, len(CALLS), sorted(i.current_state_ids), i.status,
             i.error))
    print("  plugin.on_error=%s last_error=%r" % (p.errors[:3], i.last_error))
    print("  action_errors=%d dropped=%s" % (p.action_errors, p.dropped[:3]))
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception as e:
        print("stop:", repr(e))
    # Expected safe outcome: the runaway is reported, not silent.
    sys.exit(0 if (p.errors or i.last_error is not None) else 1)


asyncio.run(main())
