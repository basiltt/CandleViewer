# -*- coding: utf-8 -*-
"""STANDALONE: B18 kill-switch shape -- an external send(priority=True)
must never be shed as `chain_budget` by an unrelated self-generated
runaway, and must preempt it (#180/#192).

`spin` re-raises SPIN from an action (a self-generated chain that trips
maxIterations); ENGAGE arrives on the priority lane from outside while the
chain spins. Pass = 0 external drops and the machine reaches `engaged`.
CV=async|def selects the service kind of the kill-switch's invoke.
"""
import asyncio, os, sys
from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.plugins import PluginBase

STYLE = os.environ.get("CV", "async")
N = int(os.environ.get("N", "40"))
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
            "clear": {"on": {"ENGAGE": {"target": "#ks.switch.cancelling",
                                        "actions": ["count_ext"]}}},
            "cancelling": {"on": {"ENGAGE": {"actions": ["count_ext"]}},
                           "invoke": {
                "id": "cx", "src": "cancel_all_working_orders",
                "onDone": {"target": "#ks.switch.engaged"},
                "onError": {"target": "#ks.switch.engaged"}}},
            "engaged": {"on": {"ENGAGE": {"actions": ["count_ext"]}}}}},
    },
}


class P(PluginBase):
    def __init__(self):
        self.dropped = []

    def on_event_dropped(self, i, e, r):
        self.dropped.append((getattr(e, "type", "?"), r))


def count_ext(i, c, e, a):
    c["ext"] = int(c.get("ext", 0)) + 1


def sd(i, c, e):
    return {"ok": True}


async def sa(i, c, e):
    return {"ok": True}


async def main():
    logic = MachineLogic(
        actions={"count_ext": count_ext},
        services={"cancel_all_working_orders": sd if STYLE == "def" else sa},
        strict=True)
    i = Interpreter(create_machine(CFG, logic=logic, strict_targets=True),
                    clock=SimulatedClock())
    p = P(); i.use(p)
    await i.start()
    await i.send("SPIN")            # light the self-generated runaway
    for _ in range(N):              # external priority traffic beside it
        await i.send("ENGAGE", priority=True)
    await asyncio.sleep(1.0)
    ext_drop = [d for d in p.dropped if d[0] == "ENGAGE"]
    print("style=%s ext_counted=%d/%d ENGAGE_dropped=%d states=%s "
          "last_error=%s" % (STYLE, i.context["ext"], N, len(ext_drop),
                             sorted(i.current_state_ids),
                             type(i.last_error).__name__))
    print("  all drops (kind,reason) sample=%s total=%d"
          % (p.dropped[:3], len(p.dropped)))
    ok = (not ext_drop and i.context["ext"] == N
          and "ks.switch.engaged" in sorted(i.current_state_ids))
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception as e:
        print("stop:", repr(e))
    sys.exit(0 if ok else 1)


asyncio.run(main())
