"""R5-10 probe (scratch): what reproduces on 3ed3099 for the guard-raise on an
engine-driven (invoke.onDone) transition, with the full mandatory config block
and the documented health signals queried."""

import asyncio
import json
import logging

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.plugins import PluginBase

R = {}


def gboom(c, e):
    raise RuntimeError("guardboom")


class Spy(PluginBase):
    def __init__(self):
        self.seen = []


for h in [a for a in dir(PluginBase) if a.startswith("on_")]:
    def mk(h):
        def f(self, *a, **k):
            self.seen.append(h)
        return f
    setattr(Spy, h, mk(h))


BLOCK = {
    "actionErrorPolicy": "rollback",
    "guardErrorPolicy": "raise",
    "onUnhandled": "ignore",
    "strictTargets": True,
    "strict": False,
    "spawnBlockingTimeout": 5.0,
}


async def svc(i, c, e):
    return {"ok": True}


async def case(name, onDone, policy="raise", declare_any=True):
    states = {"v": {"invoke": {"id": "ver", "src": "svc", "onDone": onDone}},
              "done": {}, "fallback": {}, "elsewhere": {}}
    if declare_any:
        states["v"]["on"] = {"ANY": "elsewhere"}
    cfg = {"id": name, "initial": "v", **BLOCK, "guardErrorPolicy": policy,
           "states": states}
    sp = Spy()
    i = Interpreter(create_machine(cfg, logic=MachineLogic(
        services={"svc": svc}, guards={"bad": gboom})))
    i.use(sp)
    await i.start()
    await asyncio.sleep(0.3)
    rec = {
        "ids": sorted(i.current_state_ids),
        "status": i.status,
        "error": repr(i.error),
        "last_ok": i.last_transition_ok,
        "last_error": repr(i.last_error)[:40],
        "has_dormant_invocations": i.has_dormant_invocations,
        "pending_invocations": repr(i.pending_invocations())[:100],
        "hooks": sorted(set(sp.seen)),
    }
    if declare_any:
        r = await i.send("ANY", wait=True)
        rec["further_send"] = {"changed": r.changed, "error": repr(r.error)}
        rec["ids_after"] = sorted(i.current_state_ids)
    await i.stop()
    R[name] = rec


async def main():
    # A: single guarded onDone branch, guard raises
    await case("A_single_raise", {"target": "done", "guard": "bad"})
    # B: guarded branch + unguarded fallback, policy raise
    await case("B_fallback_raise",
               [{"target": "done", "guard": "bad"}, {"target": "fallback"}])
    # C: same, policy "false" (the default)
    await case("C_fallback_false",
               [{"target": "done", "guard": "bad"}, {"target": "fallback"}],
               policy="false")


logging.disable(logging.CRITICAL)
asyncio.run(main())
print(json.dumps(R, indent=1, default=str))
