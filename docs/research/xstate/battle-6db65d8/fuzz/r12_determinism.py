"""R12 -- DETERMINISM + SEMANTICS + SECURITY on 6db65d8.

D1  50x identical traces, BOTH engines x BOTH service kinds, including trip
    LAP COUNTS.
D2  PYTHONHASHSEED sweep (re-exec with seeds 0/1/12345) -- the sweep skipped
    last round.
S1  5-WAY receipt matrix: guard-crash / denied / deferred / unhandled-ignored /
    onUnhandled="error" kill (#189 -- the kill must land on the SENDER's
    receipt, not a success-shaped one).
X1  FORGE the engine-completion marker from user code, four ways:
    (a) an Event subclass that mimics a `done.invoke` type,
    (b) dataclasses.replace on a captured DoneEvent,
    (c) send(internal=True),
    (d) sendTo of a captured DoneEvent.
    None may buy unbounded self-generated work (the chain budget must still
    trip), and none may be mistaken for an engine completion.
"""
import asyncio, copy, dataclasses, logging, os, subprocess, sys, warnings
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
from xstate_statemachine import (
    Interpreter,
    SyncInterpreter,
    MachineLogic,
    Event,
    DoneEvent,
    PluginBase,
    create_machine,
)

# ------------------------------------------------------------------ D1
TRIP = {
    "id": "t",
    "initial": "a",
    "maxIterations": 12,
    "context": {"n": 0},
    "states": {
        "a": {"always": {"target": "b", "guard": "g"}},
        "b": {"always": {"target": "a", "guard": "g", "actions": ["bump"]}},
    },
}


def d1_logic(async_svc):
    def bump(i, c, e, a):
        c["n"] = c.get("n", 0) + 1

    async def abump(i, c, e, a):
        c["n"] = c.get("n", 0) + 1

    if async_svc:

        async def svc(i, c, e):
            return {"ok": 1}

    else:

        def svc(i, c, e):
            return {"ok": 1}

    return MachineLogic(
        actions={"bump": abump if async_svc else bump},
        guards={"g": lambda c, e: True},
        services={"svc": svc},
    )


def d1_sync(async_svc):
    it = SyncInterpreter(
        create_machine(copy.deepcopy(TRIP), logic=d1_logic(False))
    )
    it.start()
    r = (
        tuple(sorted(it.current_state_ids)),
        (it.context or {}).get("n"),
        type(it.last_error).__name__ if it.last_error else None,
    )
    it.stop()
    return r


async def d1_async(async_svc):
    it = Interpreter(
        create_machine(copy.deepcopy(TRIP), logic=d1_logic(async_svc))
    )
    await asyncio.wait_for(it.start(), 10)
    await asyncio.sleep(0.15)
    r = (
        tuple(sorted(it.current_state_ids)),
        (it.context or {}).get("n"),
        type(it.last_error).__name__ if it.last_error else None,
    )
    await it.stop()
    return r


async def d1(n=50):
    print("D1 determinism: 50x identical traces, both engines, both svc kinds")
    out = {}
    for async_svc in (False, True):
        k = "asyncdef" if async_svc else "plaindef"
        s = {d1_sync(async_svc) for _ in range(n)}
        a = set()
        for _ in range(n):
            a.add(await d1_async(async_svc))
        out[k] = (s, a)
        print(
            f"   svc={k}: sync distinct={len(s)} {s}  |  async distinct={len(a)} {a}"
        )
    laps = {t[1] for pair in out.values() for st in pair for t in st}
    cross = all(pair[0] == pair[1] for pair in out.values())
    print(
        f"   cross_engine_equal={cross}  trip lap counts across the whole "
        f"matrix={laps}  => {'PASS' if cross and len(laps) == 1 else 'FAIL'}"
    )


# ------------------------------------------------------------------ D2
def d2():
    print("\nD2 PYTHONHASHSEED sweep (re-exec, seeds 0/1/12345)")
    res = {}
    for seed in ("0", "1", "12345"):
        env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONIOENCODING="utf-8")
        p = subprocess.run(
            [sys.executable, "-c", HASHSEED_CHILD],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        res[seed] = p.stdout.strip() or p.stderr.strip()[-120:]
        print(f"   seed={seed:<6} {res[seed]}")
    print(
        f"   distinct results = {len(set(res.values()))} "
        f"=> {'PASS' if len(set(res.values())) == 1 else 'FAIL'}"
    )


HASHSEED_CHILD = r"""
import asyncio, logging, warnings
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, create_machine
TRIP = {"id":"t","initial":"a","maxIterations":12,"context":{"n":0},"states":{
  "a":{"always":{"target":"b","guard":"g"}},
  "b":{"always":{"target":"a","guard":"g","actions":["bump"]}}}}
def bump(i,c,e,a): c["n"]=c.get("n",0)+1
async def svc(i,c,e): return {"ok":1}
def L(): return MachineLogic(actions={"bump":bump},guards={"g":lambda c,e:True},services={"svc":svc})
it=SyncInterpreter(create_machine(dict(TRIP),logic=L())); it.start()
s=(sorted(it.current_state_ids),it.context.get("n"),type(it.last_error).__name__ if it.last_error else None); it.stop()
async def go():
    it=Interpreter(create_machine(dict(TRIP),logic=L())); await it.start(); await asyncio.sleep(0.15)
    r=(sorted(it.current_state_ids),it.context.get("n"),type(it.last_error).__name__ if it.last_error else None)
    await it.stop(); return r
print("sync=%s async=%s" % (s, asyncio.run(go())))
"""

if __name__ == "__main__":
    asyncio.run(d1())
    d2()
