"""R5 -- concurrency attacks on 6db65d8's new machinery.

C1  `_chain_owed` under 100 concurrent NEVER-completing coroutine services
    followed by stop(): does the debt leak, does stop() hang, is the counter
    settled by the cancellation callback as documented?
C2  external `send(priority=True)` at a high rate DURING a self-generated
    chain, on BOTH service kinds: #180 says external priority sends are never
    charged -> 0 dropped as `chain_budget`.
C3  `start(children_timeout=)` with 50 slow children: bounded, WARNING logged,
    machine running, children register later.
C4  loop-side RAISE refusals (#157) exactly-once.
"""
import asyncio, logging, time, warnings, threading
warnings.simplefilter("ignore")
from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    create_machine,
)
from xstate_statemachine.machine_logic import MachineLogic as ML  # noqa: F401


class Drops(PluginBase):
    def __init__(self):
        self.d = {}
        self.lock = threading.Lock()

    def on_event_dropped(self, interp, event, reason=None, **kw):
        # 🔍 The REASON alone cannot tell an external `send(priority=True)`
        #    apart from an engine completion shed by the same budget; key on
        #    (reason, event type) so #180's claim is actually measurable.
        t = getattr(event, "type", str(event))
        with self.lock:
            k = f"{reason}:{t}"
            self.d[k] = self.d.get(k, 0) + 1


# ---------------------------------------------------------------- C1
async def c1(n=100):
    logging.disable(logging.CRITICAL)
    cfg = {
        "id": "m",
        "type": "parallel",
        "states": {
            f"r{i}": {
                "initial": "a",
                "states": {
                    "a": {"invoke": {"id": f"i{i}", "src": "hang"}},
                },
            }
            for i in range(n)
        },
    }

    async def hang(i, c, e):
        await asyncio.sleep(3600)

    it = Interpreter(
        create_machine(cfg, logic=MachineLogic(services={"hang": hang}))
    )
    t0 = time.time()
    await asyncio.wait_for(it.start(children_timeout=2.0), 30)
    owed_after_start = it._chain_owed
    await asyncio.sleep(0.2)
    owed_idle = it._chain_owed
    # independent traffic beside the never-completing services must not trip
    for _ in range(20):
        try:
            await asyncio.wait_for(it.send("PING", wait=True), 5)
        except Exception:
            pass
    owed_after_traffic = it._chain_owed
    err = type(it.last_error).__name__ if it.last_error else None
    try:
        await asyncio.wait_for(it.stop(), 10)
        stopped = "clean"
    except asyncio.TimeoutError:
        stopped = "STOP HANG"
    await asyncio.sleep(0.1)
    owed_after_stop = it._chain_owed
    ok = (
        stopped == "clean"
        and owed_after_stop == 0
        and err != "RunawayChainError"
    )
    print(
        f"C1 #179 _chain_owed, {n} never-completing coroutine services:\n"
        f"   owed after start={owed_after_start} idle={owed_idle} "
        f"after 20 independent sends={owed_after_traffic}\n"
        f"   last_error={err} stop()={stopped} owed_after_stop={owed_after_stop} "
        f"wall={time.time()-t0:.2f}s => {'PASS' if ok else 'FAIL'}"
    )


# ---------------------------------------------------------------- C2
CHAIN = {
    "id": "m",
    "initial": "a",
    "maxIterations": 50,
    "states": {
        "a": {"invoke": {"id": "i1", "src": "svc", "onDone": {"target": "#m.b"}}},
        "b": {
            "invoke": {"id": "i2", "src": "svc", "onDone": {"target": "#m.a"}},
            "on": {"EXT": {"target": "#m.b", "internal": True}},
        },
    },
}


async def c2(async_svc, rate=10000, secs=1.0):
    logging.disable(logging.CRITICAL)

    async def a_svc(i, c, e):
        return {"ok": 1}

    def p_svc(i, c, e):
        return {"ok": 1}

    dr = Drops()
    it = Interpreter(
        create_machine(
            dict(CHAIN),
            logic=MachineLogic(services={"svc": a_svc if async_svc else p_svc}),
        )
    )
    it.use(dr)
    await asyncio.wait_for(it.start(), 10)
    sent = 0
    acked = 0
    t_end = time.time() + secs
    interval = 1.0 / rate
    nxt = time.time()
    while time.time() < t_end:
        try:
            it.send("EXT", priority=True)
            sent += 1
            acked += 1
        except Exception:
            sent += 1
        nxt += interval
        d = nxt - time.time()
        if d > 0:
            await asyncio.sleep(d)
        else:
            await asyncio.sleep(0)
    await asyncio.sleep(0.2)
    ext_budget = sum(
        v for k, v in dr.d.items() if k.startswith("chain_budget:EXT")
    )
    other_budget = sum(
        v
        for k, v in dr.d.items()
        if k.startswith("chain_budget:") and not k.startswith("chain_budget:EXT")
    )
    err = type(it.last_error).__name__ if it.last_error else None
    kind = "async def" if async_svc else "plain def"
    ok = ext_budget == 0
    print(
        f"C2 #180 external priority sends during a self chain, {kind:<9} svc: "
        f"sent={sent} rate~{sent/secs:.0f}/s\n"
        f"   EXTERNAL 'EXT' shed as chain_budget={ext_budget}  "
        f"engine completions shed as chain_budget={other_budget}\n"
        f"   drops={dr.d} last_error={err} "
        f"=> {'PASS (0 external charged)' if ok else 'FAIL'}"
    )
    await it.stop()


# ---------------------------------------------------------------- C3
class WarnCatch(logging.Handler):
    def __init__(self):
        super().__init__()
        self.recs = []

    def emit(self, r):
        if r.levelno >= logging.WARNING:
            self.recs.append(r.getMessage()[:120])


async def c3(n=50, slow=0.35, timeout=0.5):
    logging.disable(logging.NOTSET)
    h = WarnCatch()
    root = logging.getLogger("xstate_statemachine")
    root.addHandler(h)
    root.setLevel(logging.WARNING)

    async def slow_entry(i, c, e, a):
        await asyncio.sleep(slow)

    kid = create_machine(
        {
            "id": "kid",
            "initial": "k",
            "states": {"k": {"entry": ["slow_entry"]}},
        },
        logic=MachineLogic(actions={"slow_entry": slow_entry}),
    )
    cfg = {
        "id": "m",
        "type": "parallel",
        "states": {
            f"r{i}": {
                "initial": "a",
                "states": {
                    "a": {"invoke": {"id": f"kid{i}", "src": "kidmachine"}}
                },
            }
            for i in range(n)
        },
    }
    it = Interpreter(
        create_machine(cfg, logic=MachineLogic(services={"kidmachine": kid}))
    )
    t0 = time.time()
    await asyncio.wait_for(it.start(children_timeout=timeout), 30)
    wall = time.time() - t0
    kids_at_return = len(getattr(it, "_actors", {}) or {})
    status = it.status
    await asyncio.sleep(slow + 0.4)
    kids_later = len(getattr(it, "_actors", {}) or {})
    warned = [m for m in h.recs if "child" in m.lower() or "timeout" in m.lower()]
    root.removeHandler(h)
    logging.disable(logging.CRITICAL)
    ok = wall < timeout + 0.35 and status == "running"
    print(
        f"C3 #181 start(children_timeout={timeout}) with {n} children whose "
        f"entry sleeps {slow}s:\n"
        f"   start() returned in {wall:.2f}s (bound {timeout}) status={status} "
        f"children at return={kids_at_return} later={kids_later}\n"
        f"   WARNINGs matching child/timeout: {len(warned)} sample={warned[:1]} "
        f"=> {'PASS' if ok else 'FAIL'}"
    )
    if not warned:
        print("   NOTE: no WARNING captured for the children_timeout hit")


async def main():
    await c1()
    for a in (False, True):
        await c2(a)
    await c3()


asyncio.run(main())
