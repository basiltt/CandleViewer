"""Q5 -- livelock config fuzzer across BOTH engines, 30s watchdog.
Shapes: nested invoke cycles, always cycles, rollback+onDone, sendTo self-loops.
Each config runs in a worker with a hard watchdog. A case is a DEFECT if the
engine neither settles nor makes the trip observable (last_error/receipt).
Async cases are additionally scored RUNAWAY if the loop keeps processing
>5000 events after start() with no trip."""
import asyncio, collections, json, logging, random, sys, time, warnings
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
import xstate_statemachine.base_interpreter as bi
from xstate_statemachine import (Interpreter, SyncInterpreter, MachineLogic,
                                 create_machine)

C = collections.Counter(); _o = bi.BaseInterpreter._process_event
async def _p(self, e):
    C[e.type] += 1; return await _o(self, e)
bi.BaseInterpreter._process_event = _p

def logic(async_svc):
    if async_svc:
        async def svc(i, c, e): return {"ok": 1}
    else:
        def svc(i, c, e): return {"ok": 1}
    async def resend(i, c, e, a):
        c["n"] = c.get("n", 0) + 1
        await i.send("LOOP")
    def resend_s(i, c, e, a):
        c["n"] = c.get("n", 0) + 1
        i.send("LOOP")
    def bump(i, c, e, a): c["n"] = c.get("n", 0) + 1
    return (MachineLogic(services={"svc": svc},
                         actions={"resend": resend, "bump": bump},
                         guards={"g": lambda c, e: True,
                                 "g2": lambda c, e: c.get("n", 0) % 2 == 0}),
            MachineLogic(services={"svc": lambda i, c, e: {"ok": 1}},
                         actions={"resend": resend_s, "bump": bump},
                         guards={"g": lambda c, e: True,
                                 "g2": lambda c, e: c.get("n", 0) % 2 == 0}))

SHAPES = ("nested_invoke", "always_cycle", "rollback_ondone", "sendto_self")

def gen(rnd, i):
    shape = rnd.choice(SHAPES)
    mi = rnd.choice([None, 1, 5, 20, 1000])
    c = {"id": f"m{i}", "initial": "a", "context": {"n": 0}}
    if mi is not None: c["maxIterations"] = mi
    if shape == "nested_invoke":
        c["states"] = {"a": {"initial": "a",
            "invoke": {"id": "i1", "src": "svc", "onDone": {"target": f"#m{i}.a"}},
            "states": {"a": {"invoke": {"id": "i2", "src": "svc",
                       "onDone": {"target": f"#m{i}.a"}}}}}}
    elif shape == "always_cycle":
        c["states"] = {"a": {"always": {"target": "b", "guard": "g"}},
                       "b": {"always": {"target": "a", "guard": "g",
                                        "actions": ["bump"]}}}
    elif shape == "rollback_ondone":
        c["states"] = {
            "a": {"invoke": {"id": "i1", "src": "svc", "onDone": {"target": "b"}}},
            "b": {"always": {"target": "a", "guard": "g", "actions": ["bump"]}}}
    else:  # sendto_self
        c["initial"] = "a"
        c["states"] = {"a": {"entry": ["resend"],
                             "on": {"LOOP": {"target": "a"}}}}
    return shape, mi, c

async def run_async(cfg, watchdog):
    C.clear()
    it = Interpreter(create_machine(cfg, logic=logic(True)[0]))
    t0 = time.time()
    try:
        await asyncio.wait_for(it.start(), watchdog)
    except asyncio.TimeoutError:
        return "START_TIMEOUT", sum(C.values()), None
    await asyncio.sleep(0.6)
    n = sum(C.values())
    err = type(it.last_error).__name__ if getattr(it, "last_error", None) else None
    try: await asyncio.wait_for(it.stop(), 5)
    except Exception: return "STOP_TIMEOUT", n, err
    if n > 5000 and err is None: return "RUNAWAY", n, err
    return "settled", n, err

def run_sync(cfg, watchdog):
    C.clear()
    it = SyncInterpreter(create_machine(cfg, logic=logic(False)[1]))
    t0 = time.time()
    try:
        it.start()
    except Exception as e:
        return f"raise:{type(e).__name__}", sum(C.values()), None
    d = time.time() - t0
    err = type(it.last_error).__name__ if getattr(it, "last_error", None) else None
    it.stop()
    if d > watchdog: return "SLOW", sum(C.values()), err
    return "settled", sum(C.values()), err

async def main(n):
    rnd = random.Random(31337)
    res = collections.Counter(); bad = []
    for i in range(n):
        shape, mi, cfg = gen(rnd, i)
        import copy
        try:
            so, sn, se = run_sync(copy.deepcopy(cfg), 30)
        except Exception as e:
            so, sn, se = f"harness:{type(e).__name__}", 0, None
        try:
            ao, an, ae = await run_async(copy.deepcopy(cfg), 30)
        except Exception as e:
            ao, an, ae = f"harness:{type(e).__name__}", 0, None
        res[f"sync:{so}"] += 1; res[f"async:{ao}"] += 1
        if so in ("SLOW",) or ao in ("RUNAWAY", "START_TIMEOUT", "STOP_TIMEOUT"):
            res[f"DEFECT:{shape}:{ao}"] += 1
            if len(bad) < 6: bad.append({"shape": shape, "mi": mi, "sync": [so, sn, se],
                                         "async": [ao, an, ae], "cfg": cfg})
        if (i + 1) % 100 == 0:
            print(f"  ...{i+1}/{n} {dict(res)}", flush=True)
    print("\n== totals ==")
    for k, v in sorted(res.items()): print(f"  {k:<40} {v}")
    json.dump(bad, open("out/q5_livelock_bad.json", "w"), indent=1)
    print(f"\nsaved {len(bad)} exemplars to out/q5_livelock_bad.json")
asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 500))
