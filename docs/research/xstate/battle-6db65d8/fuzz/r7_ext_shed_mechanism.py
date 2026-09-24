"""R7 -- MECHANISM for D8-fuzz-2: #180 fixed the CHARGE side by provenance,
but the SHED side is still positional.

`_deliver_priority` no longer increments `_raise_depth` for an external
`send(..., priority=True)` (interpreter.py:2375).  But the drop test in the run
loop (interpreter.py:1598 `over = self._raise_depth > limit`, shed at :1623)
is applied to WHATEVER event was dequeued next -- and `_next_event()` drains
the priority lane FIRST.  So once a self-generated chain has pushed
`_raise_depth` over the limit, an external priority send sitting in that lane
is dropped as `chain_budget`, its receipt failed, with `last_transition_ok`
set False -- the precise failure #105 fixed on the inbox lane and #180 was
filed to keep off this one.

This script shows it deterministically, with the chain trip forced by a tiny
`maxIterations`, and checks whether the external sender can tell.
"""
import asyncio, logging, threading, warnings
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    create_machine,
)

CFG = {
    "id": "m",
    "initial": "a",
    "maxIterations": 3,  # trip almost immediately
    "states": {
        "a": {
            "invoke": {"id": "i1", "src": "svc", "onDone": {"target": "#m.b"}},
            "on": {"EXT": {"target": "#m.a", "internal": True}},
        },
        "b": {
            "invoke": {"id": "i2", "src": "svc", "onDone": {"target": "#m.a"}},
            "on": {"EXT": {"target": "#m.b", "internal": True}},
        },
    },
}


class Drops(PluginBase):
    def __init__(self):
        self.d = {}
        self.lock = threading.Lock()

    def on_event_dropped(self, interp, event, reason=None, **kw):
        with self.lock:
            k = f"{reason}:{getattr(event, 'type', event)}"
            self.d[k] = self.d.get(k, 0) + 1


async def a_svc(i, c, e):
    return {"ok": 1}


def p_svc(i, c, e):
    return {"ok": 1}


async def trial(async_svc, n=300):
    dr = Drops()
    it = Interpreter(
        create_machine(
            dict(CFG),
            logic=MachineLogic(services={"svc": a_svc if async_svc else p_svc}),
        )
    )
    it.use(dr)
    await asyncio.wait_for(it.start(), 10)
    # 🔥 Fire external priority sends WITH receipts so the sender's own
    #    surface is measured, not just the hook.
    ok = err = timeout = 0
    errs = {}
    for _ in range(n):
        try:
            await asyncio.wait_for(it.send("EXT", wait=True, priority=True), 3)
            ok += 1
        except asyncio.TimeoutError:
            timeout += 1
        except Exception as e:
            err += 1
            errs[type(e).__name__] = errs.get(type(e).__name__, 0) + 1
        await asyncio.sleep(0)
    await asyncio.sleep(0.2)
    ext_shed = sum(v for k, v in dr.d.items() if k.startswith("chain_budget:EXT"))
    kind = "async def" if async_svc else "plain def"
    print(
        f"  {kind:<9} svc, maxIterations=3, {n} external send(priority=True, wait=True):\n"
        f"     receipts ok={ok} raised={err}{errs} timeout={timeout}\n"
        f"     EXTERNAL 'EXT' shed as chain_budget = {ext_shed}   drops={dr.d}\n"
        f"     => {'PASS' if ext_shed == 0 and err == 0 else 'FAIL (external traffic charged/shed by the chain budget)'}"
    )
    await it.stop()


async def main():
    print(
        "#180: external priority sends are never charged. Shed side, though?\n"
    )
    for a in (False, True):
        await trial(a)


asyncio.run(main())
