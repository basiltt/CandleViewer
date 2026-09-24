"""R6 -- ISOLATE: are EXTERNAL `send(..., priority=True)` events charged to the
chain budget and shed as `chain_budget` when the invoked service is a plain
`def`?  #180 says accounting is by PROVENANCE ("only engine completions and
self-raised events count"), so the answer must be 0 for every service kind.

r5.C2 observed 10 external `EXT` events shed with a `plain def` service and 0
with an `async def` one.  This script:
  * ablates the service kind, the presence of a self-generated chain, and the
    external rate;
  * counts drops keyed by (reason, event type) so an external event is never
    confused with an engine completion;
  * reports the LOSS RATE of external events, which is what a producer sees.
"""
import asyncio, logging, time, warnings, threading, sys
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    create_machine,
)


class Drops(PluginBase):
    def __init__(self):
        self.d = {}
        self.lock = threading.Lock()

    def on_event_dropped(self, interp, event, reason=None, **kw):
        t = getattr(event, "type", str(event))
        with self.lock:
            k = f"{reason}:{t}"
            self.d[k] = self.d.get(k, 0) + 1


def cfg(chain: bool):
    """chain=True: a<->b invoke ping-pong (self-generated work).
    chain=False: one idle state, no self-generated work at all."""
    if chain:
        return {
            "id": "m",
            "initial": "a",
            "maxIterations": 50,
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
    return {
        "id": "m",
        "initial": "a",
        "maxIterations": 50,
        "states": {"a": {"on": {"EXT": {"target": "#m.a", "internal": True}}}},
    }


async def a_svc(i, c, e):
    return {"ok": 1}


def p_svc(i, c, e):
    return {"ok": 1}


async def trial(async_svc, chain, n=4000):
    dr = Drops()
    it = Interpreter(
        create_machine(
            cfg(chain),
            logic=MachineLogic(services={"svc": a_svc if async_svc else p_svc}),
        )
    )
    it.use(dr)
    await asyncio.wait_for(it.start(), 10)
    sent = 0
    t0 = time.time()
    for _ in range(n):
        try:
            it.send("EXT", priority=True)
        except Exception:
            pass
        sent += 1
        await asyncio.sleep(0)
    await asyncio.sleep(0.3)
    wall = time.time() - t0
    ext = sum(v for k, v in dr.d.items() if k.startswith("chain_budget:EXT"))
    eng = sum(
        v
        for k, v in dr.d.items()
        if k.startswith("chain_budget:") and not k.startswith("chain_budget:EXT")
    )
    await it.stop()
    return sent, ext, eng, dr.d, wall


async def main():
    reps = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    print("#180: an EXTERNAL send(priority=True) must NEVER be shed as chain_budget.\n")
    for chain in (True, False):
        for async_svc in (False, True):
            tot_ext = tot_sent = tot_eng = 0
            sample = None
            for _ in range(reps):
                s, e, g, d, w = await trial(async_svc, chain)
                tot_sent += s
                tot_ext += e
                tot_eng += g
                sample = sample or d
            kind = "async def" if async_svc else "plain def"
            sh = "self-chain" if chain else "NO chain  "
            print(
                f"  {sh} + {kind:<9} svc: sent={tot_sent} "
                f"EXTERNAL shed as chain_budget={tot_ext} "
                f"({100*tot_ext/max(tot_sent,1):.2f}%)  engine shed={tot_eng} "
                f"=> {'PASS' if tot_ext == 0 else 'FAIL'}"
            )
            if tot_ext:
                print(f"       drops sample: {sample}")


asyncio.run(main())
