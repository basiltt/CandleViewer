"""R18 -- D8-fuzz-3 MINIMAL: an `always` that re-enters the invoking child on
every completion spins without ever tripping the chain budget, and STARVES
external priority traffic. `async def` service only.

r17's instrumentation on the `always_into_invoke` shape:

    svc=asyncdef: status=running last_error=None
      always-transition fires    = 3042
      EXT received               =   60 of 500 sent
      EXT actions run            =    1
      queues at end: inbox=499  priority=440  (both backed up)
    svc=plaindef: same chart
      EXT received               =  500 of 500
      EXT actions run            =  486

So on the coroutine lane the machine consumes its own transient chain in
preference to 440 queued EXTERNAL priority events, reports
`last_error=None`, fires no `on_event_dropped`, and stays `"running"`. The
#180 promise ("external traffic of any volume is never throttled") and the
#179 promise ("both service kinds trip at the same lap count") both fail here
-- not by dropping, but by never getting to them.

This script is the standalone repro + the ablations that pin the cause.
"""
import asyncio, logging, warnings, collections, time
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
from xstate_statemachine import (
    Interpreter,
    SyncInterpreter,
    MachineLogic,
    PluginBase,
    create_machine,
)

C = collections.Counter()


class Spy(PluginBase):
    def on_event_received(self, interp, event):
        C[f"recv:{getattr(event,'type',event)}"] += 1

    def on_event_dropped(self, interp, event, reason=None, **kw):
        C[f"drop:{reason}"] += 1


CFG = {
    "id": "m",
    "initial": "a",
    "maxIterations": 50,
    "context": {"ext": 0},
    "on": {"EXT": {"actions": ["extbump"]}},  # root handler: always matches
    "states": {
        "a": {"on": {"GO": "b"}},
        "b": {
            "always": {"target": "b2"},
            "initial": "b2",
            "states": {
                "b2": {
                    "invoke": {"id": "s", "src": "svc", "onDone": {"target": "#m.a"}}
                }
            },
        },
    },
}


async def a_svc(i, c, e):
    await asyncio.sleep(0)
    return {"ok": 1}


def p_svc(i, c, e):
    return {"ok": 1}


def extbump(i, c, e, a):
    c["ext"] = c.get("ext", 0) + 1


def logic(async_svc):
    return MachineLogic(
        services={"svc": a_svc if async_svc else p_svc},
        actions={"extbump": extbump},
    )


async def trial(async_svc, n=500, label=""):
    C.clear()
    it = Interpreter(create_machine(dict(CFG), logic=logic(async_svc)))
    it.use(Spy())
    await asyncio.wait_for(it.start(), 10)
    t0 = time.time()
    for _ in range(n):
        await it.send("GO")
        it.send("EXT", priority=True)
        await asyncio.sleep(0)
    await asyncio.sleep(1.0)
    applied = (it.context or {}).get("ext", 0)
    err = type(it.last_error).__name__ if it.last_error else None
    kind = "async def" if async_svc else "plain def"
    print(
        f"  {kind:<9} {label:<14} EXT sent={n} received={C['recv:EXT']} "
        f"APPLIED={applied} ({100*applied/n:.1f}%)\n"
        f"                            status={it.status} last_error={err} "
        f"drops={{k:v for k,v in C.items() if k.startswith('drop')}} = "
        f"{ {k: v for k, v in C.items() if k.startswith('drop')} }\n"
        f"                            queues at end: inbox={it._event_queue.qsize()} "
        f"priority={len(it._priority_queue)} internal={len(it._internal_queue)}"
    )
    await it.stop()


def sync_trial(n=500):
    C.clear()
    it = SyncInterpreter(create_machine(dict(CFG), logic=logic(False)))
    it.use(Spy())
    it.start()
    for _ in range(n):
        try:
            it.send("GO")
            it.send("EXT", priority=True)
        except Exception:
            pass
    applied = (it.context or {}).get("ext", 0)
    err = type(it.last_error).__name__ if it.last_error else None
    print(
        f"  SYNC engine, plain def:  EXT sent={n} APPLIED={applied} "
        f"({100*applied/n:.1f}%) status={it.status} last_error={err} "
        f"drops={ {k: v for k, v in C.items() if k.startswith('drop')} }"
    )
    it.stop()


async def main():
    print(
        "An external send(priority=True) must be applied whatever the machine "
        "is doing (#180).\n"
    )
    sync_trial()
    for a in (False, True):
        await trial(a)
    # --- ablation: remove the `always`, keep the invoke cycle
    print("\nablation A: drop the `always` (invoke onDone -> a is the only cycle)")
    global CFG
    keep = dict(CFG)
    CFG = {
        **keep,
        "states": {
            "a": {"on": {"GO": "b"}},
            "b": {
                "initial": "b2",
                "states": {
                    "b2": {
                        "invoke": {
                            "id": "s",
                            "src": "svc",
                            "onDone": {"target": "#m.a"},
                        }
                    }
                },
            },
        },
    }
    for a in (False, True):
        await trial(a, label="no-always")
    # --- ablation: keep the `always`, drop the invoke
    print("\nablation B: drop the `invoke` (the `always` alone)")
    CFG = {
        **keep,
        "states": {
            "a": {"on": {"GO": "b"}},
            "b": {"always": {"target": "b2"}, "initial": "b2", "states": {"b2": {}}},
        },
    }
    for a in (False, True):
        await trial(a, label="no-invoke")


asyncio.run(main())
