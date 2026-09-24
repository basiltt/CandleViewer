"""R8 -- D8-fuzz-2 SEVERITY: is the external event that the chain budget sheds
actually LOST, and does its sender find out?

r7 showed 1 external `EXT` shed as `chain_budget` while all 300 receipts came
back `ok`. Two possibilities:
  (a) the hook fires for an event that IS still applied  -> hook noise only;
  (b) the event is dropped and the sender is told it succeeded -> silent loss.

Oracle: an entry action increments `ctx['applied']` on every EXT. Compare
    receipts_ok   vs   ctx['applied']   vs   hook drops.
Run with BOTH service kinds and fire-and-forget as well as wait=True.
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
    "maxIterations": 3,
    "context": {"applied": 0},
    "states": {
        "a": {
            "invoke": {"id": "i1", "src": "svc", "onDone": {"target": "#m.b"}},
            "on": {"EXT": {"target": "#m.a", "internal": True, "actions": ["bump"]}},
        },
        "b": {
            "invoke": {"id": "i2", "src": "svc", "onDone": {"target": "#m.a"}},
            "on": {"EXT": {"target": "#m.b", "internal": True, "actions": ["bump"]}},
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


def bump(i, c, e, a):
    if isinstance(c, dict):
        c["applied"] = c.get("applied", 0) + 1


async def a_svc(i, c, e):
    return {"ok": 1}


def p_svc(i, c, e):
    return {"ok": 1}


async def trial(async_svc, wait, n=600):
    dr = Drops()
    it = Interpreter(
        create_machine(
            dict(CFG),
            logic=MachineLogic(
                actions={"bump": bump},
                services={"svc": a_svc if async_svc else p_svc},
            ),
        )
    )
    it.use(dr)
    await asyncio.wait_for(it.start(), 10)
    ok = err = 0
    errs = {}
    for _ in range(n):
        try:
            if wait:
                await asyncio.wait_for(it.send("EXT", wait=True, priority=True), 3)
            else:
                it.send("EXT", priority=True)
            ok += 1
        except Exception as e:
            err += 1
            errs[type(e).__name__] = errs.get(type(e).__name__, 0) + 1
        await asyncio.sleep(0)
    await asyncio.sleep(0.4)
    applied = (it.context or {}).get("applied", 0)
    ext_shed = sum(v for k, v in dr.d.items() if k.startswith("chain_budget:EXT"))
    lost = n - applied
    kind = "async def" if async_svc else "plain def"
    mode = "wait=True " if wait else "fire&forget"
    verdict = (
        "PASS"
        if lost == 0
        else (
            "FAIL: SILENT LOSS (sender told ok)"
            if err == 0
            else "FAIL: loss, reported"
        )
    )
    print(
        f"  {kind:<9} {mode}: sent={n} sender_ok={ok} sender_err={err}{errs} "
        f"APPLIED={applied} LOST={lost} ext_shed_hook={ext_shed} => {verdict}"
    )
    await it.stop()


async def main():
    print("Does a chain-budget shed of an EXTERNAL priority send lose the event silently?\n")
    for a in (False, True):
        for w in (True, False):
            await trial(a, w)


asyncio.run(main())
