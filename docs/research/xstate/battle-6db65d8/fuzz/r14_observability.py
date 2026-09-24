"""R14 -- OBSERVABILITY hook matrix on 6db65d8, exactly-once + ordering, BOTH
engines, BOTH service kinds.

Reasons exercised:
  * chain_budget on the ASYNC lane (an `async def` service's completion chain
    -- the lane that was blind before #179)
  * queue_full loop-side (#157, from a foreign thread under OverflowPolicy.RAISE)
  * child=True snapshot refusal (#183): SnapshotMidStepError carrying child=True
  * children_timeout WARNING (#181)

For each: does the hook fire, exactly once per occurrence, and in the same
order/count on both engines?
"""
import asyncio, logging, threading, time, warnings, collections
warnings.simplefilter("ignore")
from xstate_statemachine import (
    Interpreter,
    SyncInterpreter,
    MachineLogic,
    PluginBase,
    create_machine,
)
from xstate_statemachine.exceptions import SnapshotMidStepError


class Hooks(PluginBase):
    def __init__(self):
        self.seq = []
        self.c = collections.Counter()
        self.lock = threading.Lock()

    def on_event_dropped(self, interp, event, reason=None, **kw):
        with self.lock:
            self.c[f"drop:{reason}"] += 1
            self.seq.append(f"drop:{reason}")

    def on_transition_failed(self, interp, event, error=None, **kw):
        with self.lock:
            self.c[f"failed:{type(error).__name__ if error else None}"] += 1


# ---------------------------------------------------------- A: chain_budget
CHAIN = {
    "id": "m",
    "initial": "a",
    "maxIterations": 10,
    "states": {
        "a": {"invoke": {"id": "i1", "src": "svc", "onDone": {"target": "#m.b"}}},
        "b": {"invoke": {"id": "i2", "src": "svc", "onDone": {"target": "#m.a"}}},
    },
}


def svcs(async_svc):
    async def a(i, c, e):
        return {"ok": 1}

    def p(i, c, e):
        return {"ok": 1}

    return {"svc": a if async_svc else p}


async def a_async(async_svc):
    logging.disable(logging.CRITICAL)
    h = Hooks()
    it = Interpreter(
        create_machine(dict(CHAIN), logic=MachineLogic(services=svcs(async_svc)))
    )
    it.use(h)
    await asyncio.wait_for(it.start(), 10)
    await asyncio.sleep(1.0)
    err = type(it.last_error).__name__ if it.last_error else None
    await it.stop()
    return h.c["drop:chain_budget"], err


def a_sync():
    logging.disable(logging.CRITICAL)
    h = Hooks()
    it = SyncInterpreter(
        create_machine(dict(CHAIN), logic=MachineLogic(services=svcs(False)))
    )
    it.use(h)
    it.start()
    err = type(it.last_error).__name__ if it.last_error else None
    it.stop()
    return h.c["drop:chain_budget"], err


# ---------------------------------------------------------- B: queue_full
async def b_queue_full(async_svc, threads=8, per=80):
    from xstate_statemachine import OverflowPolicy

    logging.disable(logging.CRITICAL)
    h = Hooks()

    async def slow(i, c, e, a):
        await asyncio.sleep(0.05)

    it = Interpreter(
        create_machine(
            {
                "id": "q",
                "initial": "a",
                "states": {"a": {"on": {"GO": {"target": "a", "actions": ["slow"]}}}},
            },
            logic=MachineLogic(actions={"slow": slow}, services=svcs(async_svc)),
        ),
        max_queue_size=2,
        overflow_policy=OverflowPolicy.RAISE,
    )
    it.use(h)
    await asyncio.wait_for(it.start(), 10)
    loop = asyncio.get_running_loop()
    futs = []
    errs = collections.Counter()

    def worker():
        for _ in range(per):
            try:
                futs.append(it.send_threadsafe("GO"))
            except Exception as e:
                errs[type(e).__name__] += 1

    ts = [threading.Thread(target=worker) for _ in range(threads)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    await asyncio.sleep(1.5)
    fut_err = 0
    for f in futs:
        try:
            if f.done() and f.exception() is not None:
                fut_err += 1
        except Exception:
            fut_err += 1
    await it.stop()
    return len(futs), fut_err, h.c["drop:queue_full"], dict(errs)


# ---------------------------------------------------------- C: child=True
async def c_child_refusal(async_svc):
    logging.disable(logging.CRITICAL)
    seen = {"root": None, "child": None}

    async def kid_entry(i, c, e, a):
        # snapshot the PARENT from inside the child's entry action
        p = getattr(i, "parent", None) or i
        try:
            p.get_persisted_snapshot()
            seen["child"] = "PRODUCED"
        except SnapshotMidStepError as ex:
            seen["child"] = f"REFUSED child={getattr(ex, 'child', 'n/a')}"
        except Exception as ex:
            seen["child"] = f"OTHER:{type(ex).__name__}"

    kid = create_machine(
        {"id": "kid", "initial": "k", "states": {"k": {"entry": ["ke"]}}},
        logic=MachineLogic(actions={"ke": kid_entry}),
    )
    it = Interpreter(
        create_machine(
            {
                "id": "p",
                "initial": "a",
                "states": {"a": {"invoke": {"id": "kid", "src": "km"}}},
            },
            logic=MachineLogic(services={"km": kid}),
        )
    )
    await asyncio.wait_for(it.start(children_timeout=2.0), 10)
    await asyncio.sleep(0.2)
    await it.stop()
    return seen


# ---------------------------------------------------------- D: children_timeout
class Warns(logging.Handler):
    def __init__(self):
        super().__init__()
        self.recs = []

    def emit(self, r):
        if r.levelno >= logging.WARNING:
            self.recs.append(r.getMessage()[:150])


async def d_children_timeout(n=50, slow=0.6, to=0.2):
    logging.disable(logging.NOTSET)
    h = Warns()
    lg = logging.getLogger("xstate_statemachine")
    lg.addHandler(h)
    lg.setLevel(logging.WARNING)

    async def slow_entry(i, c, e, a):
        await asyncio.sleep(slow)

    kid = create_machine(
        {"id": "kid", "initial": "k", "states": {"k": {"entry": ["se"]}}},
        logic=MachineLogic(actions={"se": slow_entry}),
    )
    it = Interpreter(
        create_machine(
            {
                "id": "p",
                "type": "parallel",
                "states": {
                    f"r{i}": {
                        "initial": "a",
                        "states": {"a": {"invoke": {"id": f"k{i}", "src": "km"}}},
                    }
                    for i in range(n)
                },
            },
            logic=MachineLogic(services={"km": kid}),
        )
    )
    t0 = time.time()
    await asyncio.wait_for(it.start(children_timeout=to), 30)
    wall = time.time() - t0
    await asyncio.sleep(slow + 0.3)
    await it.stop()
    lg.removeHandler(h)
    logging.disable(logging.CRITICAL)
    rel = [m for m in h.recs if "child" in m.lower() or "timeout" in m.lower()]
    return wall, len(h.recs), rel[:2]


async def main():
    print("A chain_budget hook, both engines, both service kinds (#179 async lane)")
    sc, se = a_sync()
    for a in (False, True):
        ac, ae = await a_async(a)
        k = "asyncdef" if a else "plaindef"
        print(
            f"   svc={k}: sync chain_budget={sc} (err={se})  "
            f"async chain_budget={ac} (err={ae})  "
            f"=> {'PASS exactly-once, parity' if sc == ac == 1 else 'see counts'}"
        )

    print("\nB queue_full loop-side (#157), OverflowPolicy.RAISE, 8 threads x 80")
    for a in (False, True):
        sent, fut_err, hook, call_err = await b_queue_full(a)
        k = "asyncdef" if a else "plaindef"
        tot = fut_err + sum(call_err.values())
        print(
            f"   svc={k}: futures={sent} future_errors={fut_err} "
            f"call_site_raises={call_err} hook queue_full={hook} "
            f"=> {'PASS exactly-once' if hook == tot else f'MISMATCH hook={hook} refused={tot}'}"
        )

    print("\nC child=True snapshot refusal (#183)")
    for a in (False, True):
        r = await c_child_refusal(a)
        print(f"   svc={'asyncdef' if a else 'plaindef'}: {r}")

    print("\nD children_timeout WARNING (#181), 50 children, entry 0.6s, timeout 0.2s")
    wall, nwarn, sample = await d_children_timeout()
    print(
        f"   start() returned in {wall:.2f}s  WARNINGs={nwarn} relevant_sample={sample} "
        f"=> {'PASS (bounded + warned)' if wall < 0.6 and sample else 'bounded but NOT warned' if wall < 0.6 else 'FAIL'}"
    )


asyncio.run(main())
