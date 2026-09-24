"""R11 -- LIVELOCK FUZZER, the full matrix the brief asks for:
   >= 500 configs  x  {plain def, async def} services  x  {sync, async} engines
with a 30 s watchdog.  Shapes: nested invoke cycles, `always` cycles,
rollback+onDone, sendTo self-loops, and PRIORITY self-sends.

q5 (the prior round's fuzzer) only ever ran the async engine with an
`async def` service and the sync engine with a `def` one, so the
(async engine, plain def) and (sync engine, async def) cells were never
scored. This script scores all four.

Three properties are checked per config:
  P1 TERMINATION -- the engine settles within the watchdog.
  P2 OBSERVABILITY -- every trip is visible on at least one of
     last_error / receipt.error / on_event_dropped(chain_budget).
  P3 LAP PARITY -- the lap count (events processed) is EQUAL across the two
     engines for the same config and service kind, as #179 promises.

Usage: r11_livelock_matrix.py [N]
"""
import asyncio, collections, copy, json, logging, random, sys, time, warnings
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
import xstate_statemachine.base_interpreter as bi
from xstate_statemachine import (
    Interpreter,
    SyncInterpreter,
    MachineLogic,
    PluginBase,
    create_machine,
)

C = collections.Counter()
_o = bi.BaseInterpreter._process_event


async def _p(self, e):
    C[e.type] += 1
    return await _o(self, e)


bi.BaseInterpreter._process_event = _p


class Drops(PluginBase):
    def __init__(self):
        self.d = collections.Counter()

    def on_event_dropped(self, interp, event, reason=None, **kw):
        self.d[str(reason)] += 1


def logic(async_svc, sync_engine):
    """Both service kinds, for both engines. A coroutine service on the SYNC
    engine is rejected by the library (NotSupportedError) -- recorded, not a
    defect."""
    if async_svc:

        async def svc(i, c, e):
            return {"ok": 1}

    else:

        def svc(i, c, e):
            return {"ok": 1}

    def bump(i, c, e, a):
        c["n"] = c.get("n", 0) + 1

    if sync_engine:

        def resend(i, c, e, a):
            c["n"] = c.get("n", 0) + 1
            i.send("LOOP")

        def presend(i, c, e, a):
            c["n"] = c.get("n", 0) + 1
            i.send("LOOP")

    else:

        async def resend(i, c, e, a):
            c["n"] = c.get("n", 0) + 1
            await i.send("LOOP")

        async def presend(i, c, e, a):
            c["n"] = c.get("n", 0) + 1
            i.send("LOOP", priority=True)

    return MachineLogic(
        services={"svc": svc},
        actions={"resend": resend, "presend": presend, "bump": bump},
        guards={"g": lambda c, e: True, "g2": lambda c, e: c.get("n", 0) % 2 == 0},
    )


SHAPES = (
    "nested_invoke",
    "always_cycle",
    "rollback_ondone",
    "sendto_self",
    "priority_self",
)


def gen(rnd, i):
    shape = rnd.choice(SHAPES)
    mi = rnd.choice([None, 1, 5, 20, 1000])
    c = {"id": f"m{i}", "initial": "a", "context": {"n": 0}}
    if mi is not None:
        c["maxIterations"] = mi
    if shape == "nested_invoke":
        c["states"] = {
            "a": {
                "initial": "a",
                "invoke": {"id": "i1", "src": "svc", "onDone": {"target": f"#m{i}.a"}},
                "states": {
                    "a": {
                        "invoke": {
                            "id": "i2",
                            "src": "svc",
                            "onDone": {"target": f"#m{i}.a"},
                        }
                    }
                },
            }
        }
    elif shape == "always_cycle":
        c["states"] = {
            "a": {"always": {"target": "b", "guard": "g"}},
            "b": {"always": {"target": "a", "guard": "g", "actions": ["bump"]}},
        }
    elif shape == "rollback_ondone":
        c["states"] = {
            "a": {"invoke": {"id": "i1", "src": "svc", "onDone": {"target": "b"}}},
            "b": {"always": {"target": "a", "guard": "g", "actions": ["bump"]}},
        }
    elif shape == "sendto_self":
        c["states"] = {
            "a": {"entry": ["resend"], "on": {"LOOP": {"target": "a"}}}
        }
    else:  # priority_self
        c["states"] = {
            "a": {"entry": ["presend"], "on": {"LOOP": {"target": "a"}}}
        }
    return shape, mi, c


async def run_async(cfg, async_svc, watchdog=30):
    C.clear()
    dr = Drops()
    try:
        it = Interpreter(
            create_machine(copy.deepcopy(cfg), logic=logic(async_svc, False))
        )
    except Exception as e:
        return f"build:{type(e).__name__}", 0, None, dr.d
    it.use(dr)
    try:
        await asyncio.wait_for(it.start(children_timeout=1.0), watchdog)
    except asyncio.TimeoutError:
        return "START_TIMEOUT", sum(C.values()), None, dr.d
    except Exception as e:
        return f"start:{type(e).__name__}", 0, None, dr.d
    # ⏳ Poll to QUIESCENCE rather than sampling a fixed 0.6 s, or a chart
    #    that is merely slow is scored with a truncated lap count and the
    #    parity comparison below measures the sampling window, not the
    #    engine. Quiescent = lap count unchanged over 3 consecutive 0.1 s
    #    samples; bounded by the watchdog.
    prev, stable, t0 = -1, 0, time.time()
    while time.time() - t0 < watchdog:
        await asyncio.sleep(0.1)
        cur = sum(C.values())
        stable = stable + 1 if cur == prev else 0
        prev = cur
        if stable >= 3:
            break
    n = sum(C.values())
    err = type(it.last_error).__name__ if getattr(it, "last_error", None) else None
    try:
        await asyncio.wait_for(it.stop(), 5)
    except Exception:
        return "STOP_TIMEOUT", n, err, dr.d
    if n > 5000 and err is None and not dr.d:
        return "RUNAWAY", n, err, dr.d
    return "settled", n, err, dr.d


def run_sync(cfg, async_svc, watchdog=30):
    C.clear()
    dr = Drops()
    try:
        it = SyncInterpreter(
            create_machine(copy.deepcopy(cfg), logic=logic(async_svc, True))
        )
    except Exception as e:
        return f"build:{type(e).__name__}", 0, None, dr.d
    it.use(dr)
    t0 = time.time()
    try:
        it.start()
    except Exception as e:
        return f"raise:{type(e).__name__}", sum(C.values()), None, dr.d
    d = time.time() - t0
    err = type(it.last_error).__name__ if getattr(it, "last_error", None) else None
    try:
        it.stop()
    except Exception:
        pass
    if d > watchdog:
        return "SLOW", sum(C.values()), err, dr.d
    return "settled", sum(C.values()), err, dr.d


async def main(n):
    rnd = random.Random(31337)
    res = collections.Counter()
    unobservable = []
    parity_bad = []
    bad = []
    for i in range(n):
        shape, mi, cfg = gen(rnd, i)
        laps = {}
        for async_svc in (False, True):
            k = "asyncdef" if async_svc else "plaindef"
            try:
                so, sn, se, sd = run_sync(cfg, async_svc)
            except Exception as e:
                so, sn, se, sd = f"harness:{type(e).__name__}", 0, None, {}
            try:
                ao, an, ae, ad = await run_async(cfg, async_svc)
            except Exception as e:
                ao, an, ae, ad = f"harness:{type(e).__name__}", 0, None, {}
            res[f"sync/{k}:{so}"] += 1
            res[f"async/{k}:{ao}"] += 1
            # P2 observability: a run that burned many laps must show a trip
            for eng, o, nn, ee, dd in (
                ("sync", so, sn, se, sd),
                ("async", ao, an, ae, ad),
            ):
                if nn > 2000 and ee is None and not dd:
                    unobservable.append(
                        {"i": i, "shape": shape, "mi": mi, "engine": eng, "svc": k, "laps": nn}
                    )
            # P3 lap parity (only where both engines actually ran the config)
            if so == "settled" and ao == "settled" and sn and an:
                laps[k] = (sn, an)
                if sn != an:
                    parity_bad.append(
                        {"i": i, "shape": shape, "mi": mi, "svc": k, "sync": sn, "async": an}
                    )
            if so == "SLOW" or ao in ("RUNAWAY", "START_TIMEOUT", "STOP_TIMEOUT"):
                res[f"DEFECT:{shape}:{k}:{ao}"] += 1
                if len(bad) < 8:
                    bad.append(
                        {
                            "shape": shape,
                            "mi": mi,
                            "svc": k,
                            "sync": [so, sn, se],
                            "async": [ao, an, ae],
                            "cfg": cfg,
                        }
                    )
        if (i + 1) % 100 == 0:
            print(
                f"  ...{i+1}/{n} runaway={sum(v for k,v in res.items() if 'RUNAWAY' in k)} "
                f"unobservable={len(unobservable)} parity_bad={len(parity_bad)}",
                flush=True,
            )
    print(f"\n== totals over {n} configs x 2 service kinds x 2 engines ==")
    for k, v in sorted(res.items()):
        print(f"  {k:<42} {v}")
    print(f"\nP2 UNOBSERVABLE trips (>2000 laps, no error and no drop hook): {len(unobservable)}")
    for r in unobservable[:6]:
        print(f"   {r}")
    print(f"\nP3 LAP-PARITY mismatches sync vs async: {len(parity_bad)}")
    pc = collections.Counter((r["shape"], r["svc"]) for r in parity_bad)
    for k, v in pc.most_common(10):
        print(f"   {k}: {v}")
    for r in parity_bad[:6]:
        print(f"   {r}")
    json.dump(
        {"bad": bad, "unobservable": unobservable, "parity": parity_bad[:50]},
        open("out/r11_livelock.json", "w"),
        indent=1,
    )
    print("\nsaved out/r11_livelock.json")


asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 500))
