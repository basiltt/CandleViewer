"""R8-04 refutation probe.

Q1: is the `always` in the repro chart a VALID chart, or the documented
    infinite-loop misuse (eventless transition that is permanently enabled
    and re-enters its own source)?  Instrument: count always firings while
    the machine sits in `b` with NO external traffic at all.
Q2: does CORRECT usage (guarded `always`, so it is enabled at most once per
    entry) show any starvation, on BOTH def and async def?
Q3: does a FAST legitimate invoke cycle (no always) starve externals?
"""
import asyncio, logging, warnings, collections, time
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
from xstate_statemachine import Interpreter, MachineLogic, PluginBase, create_machine

C = collections.Counter()


class Spy(PluginBase):
    def on_event_dropped(self, interp, event, reason=None, **kw):
        C[f"drop:{reason}:{getattr(event,'type','?')}"] += 1


def mk(always_block):
    return {
        "id": "m", "initial": "a", "maxIterations": 50,
        "context": {"ext": 0, "loops": 0},
        "on": {"EXT": {"actions": ["extbump"]}},
        "states": {
            "a": {"on": {"GO": "b"}},
            "b": {**always_block, "initial": "b2",
                  "states": {"b2": {"invoke": {"id": "s", "src": "svc",
                                               "onDone": {"target": "#m.a"}}}}},
        },
    }


async def a_svc(i, c, e):
    await asyncio.sleep(0); return {"ok": 1}


def p_svc(i, c, e):
    return {"ok": 1}


def extbump(i, c, e, a): c["ext"] = c.get("ext", 0) + 1
def loopbump(i, c, e, a): c["loops"] = c.get("loops", 0) + 1
def notyet(i, c, e): return c.get("loops", 0) < 1   # guard: fire once per run


def logic(asyncsvc):
    return MachineLogic(services={"svc": a_svc if asyncsvc else p_svc},
                        actions={"extbump": extbump, "loopbump": loopbump},
                        guards={"notyet": notyet})


async def trial(cfg, asyncsvc, label, n=300, quiet=False):
    C.clear()
    it = Interpreter(create_machine(dict(cfg), logic=logic(asyncsvc)))
    it.use(Spy())
    await asyncio.wait_for(it.start(), 10)
    if quiet:  # Q1: no external traffic, one GO, watch the loop counter
        await it.send("GO")
        await asyncio.sleep(1.0)
        print(f"  {label:<26} {'async def' if asyncsvc else 'plain def':<9} "
              f"always-fired={(it.context or {}).get('loops',0)} in 1s "
              f"(no external traffic) err={type(it.last_error).__name__ if it.last_error else None}")
        await it.stop(); return
    for _ in range(n):
        await it.send("GO")
        it.send("EXT", priority=True)
        await asyncio.sleep(0)
    await asyncio.sleep(1.0)
    ap = (it.context or {}).get("ext", 0)
    print(f"  {label:<26} {'async def' if asyncsvc else 'plain def':<9} "
          f"EXT applied={ap}/{n} ({100*ap/n:.0f}%) inbox={it._event_queue.qsize()} "
          f"prio={len(it._priority_queue)} err={type(it.last_error).__name__ if it.last_error else None} "
          f"drops={dict(C)}")
    await it.stop()


async def main():
    BAD = mk({"always": {"target": "b2", "actions": ["loopbump"]}})
    GUARDED = mk({"always": {"target": "b2", "guard": "notyet", "actions": ["loopbump"]}})
    NONE = mk({})
    print("Q1: is the repro's `always` a permanently-enabled self re-entry?")
    for a in (False, True):
        await trial(BAD, a, "unguarded always", quiet=True)
    for a in (False, True):
        await trial(GUARDED, a, "guarded always", quiet=True)
    print("\nQ2: external traffic under CORRECT usage (guarded always + invoke)")
    for a in (False, True):
        await trial(GUARDED, a, "guarded always")
    print("\nQ3: external traffic, fast invoke cycle, no always")
    for a in (False, True):
        await trial(NONE, a, "no always")
    print("\nControl: the repro chart as filed")
    for a in (False, True):
        await trial(BAD, a, "unguarded always")


asyncio.run(main())
