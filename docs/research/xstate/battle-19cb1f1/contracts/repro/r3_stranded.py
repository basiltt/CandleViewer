# -*- coding: utf-8 -*-
"""STANDALONE: after the rollback+onDone runaway is shed, is the machine
stranded in `submitting` with a completed service, or does it recover?

Adds an escape hatch event ABORT on `submitting` and a live-ness probe
after the chain has tripped. CV=async|def.
"""
import asyncio, os, sys
from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.plugins import PluginBase

STYLE = os.environ.get("CV", "async")
CFG = {
    "id": "order", "initial": "submitting", "maxIterations": 25,
    "actionErrorPolicy": "rollback", "onUnhandled": "defer",
    "guardErrorPolicy": "raise", "strictTargets": True, "strict": True,
    "context": {},
    "states": {
        "submitting": {
            "on": {"ABORT": {"target": "#order.unknown"}},
            "invoke": {"id": "po", "src": "place_order",
                       "onDone": {"target": "#order.submitted"},
                       "onError": {"target": "#order.unknown"}}},
        "submitted": {"entry": ["adopt_ack"]},
        "unknown": {"type": "final"},
    },
}
CALLS = []


class P(PluginBase):
    def __init__(self):
        self.dropped = []

    def on_event_dropped(self, i, e, r):
        self.dropped.append((getattr(e, "type", "?"), r))


def adopt_ack(i, c, e, a):
    raise RuntimeError("boom")


def sd(i, c, e):
    CALLS.append(1); return {"ok": True}


async def sa(i, c, e):
    CALLS.append(1); return {"ok": True}


async def main():
    logic = MachineLogic(actions={"adopt_ack": adopt_ack},
                         services={"place_order": sd if STYLE == "def" else sa},
                         strict=True)
    i = Interpreter(create_machine(CFG, logic=logic, strict_targets=True),
                    clock=SimulatedClock())
    p = P(); i.use(p)
    await i.start()
    await asyncio.sleep(2.0)
    settled_calls, settled = len(CALLS), sorted(i.current_state_ids)
    await asyncio.sleep(1.0)
    quiet = len(CALLS) == settled_calls
    # is the machine still responsive after the shed?
    try:
        await asyncio.wait_for(i.send("ABORT", wait=True), 5)
        resp = True
    except Exception as e:
        resp = repr(e)
    await asyncio.sleep(0.2)
    print("style=%s calls=%d parked=%s quiet_after=%s dropped=%s"
          % (STYLE, settled_calls, settled, quiet, p.dropped[:2]))
    print("  after ABORT: send=%s states=%s status=%s error=%r"
          % (resp, sorted(i.current_state_ids), i.status, i.error))
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception as e:
        print("stop:", repr(e))
    sys.exit(1 if settled != ["order.unknown"] else 0)


asyncio.run(main())
