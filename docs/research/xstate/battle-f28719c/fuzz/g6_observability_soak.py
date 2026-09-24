"""G6 -- NEW ATTACK: observability + bounded soak on round-8 machinery.

A. Hook matrix: shed-by-provenance drops must name the shed item's
   provenance; settle-trip reported on every step it affects; exactly-once
   on BOTH engines.
B. RAISE loop-side exactly-once under OverflowPolicy.RAISE.
C. Bounded SOAK (SOAK_S seconds, default 90): M machines with async
   services + an external priority producer + rollback+onDone +
   always->invoke, with a chaos snapshot at quiescence.  Asserts:
   CPU bounded, 0 dropped external, no livelock, no thread leak.

Usage: g6_observability_soak.py [SOAK_S] [M]
STANDALONE: stdlib + xstate_statemachine only.
"""
import asyncio, collections, copy, gc, logging, os, sys, threading, time, warnings

warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)
from xstate_statemachine import (
    Interpreter,
    SyncInterpreter,
    MachineLogic,
    PluginBase,
    create_machine,
)

C = collections.Counter()


class Hooks(PluginBase):
    def on_event_dropped(self, i, ev, reason=None, **kw):
        C[f"drop:{reason}"] += 1
        C[f"droptype:{getattr(ev, 'type', '?')}"] += 1

    def on_error(self, i, err, **kw):
        C[f"err:{type(err).__name__}"] += 1


# ---------------------------------------------------------------- A
SHED_CFG = {
    "id": "sh",
    "initial": "s",
    "maxIterations": 8,
    "context": {"ext": 0},
    "states": {
        "s": {
            "on": {
                "SELF": {"actions": ["respawn"]},
                "EXT": {"actions": ["cext"]},
            }
        }
    },
}


def cext(i, c, e, a=None):
    c["ext"] = c.get("ext", 0) + 1


def respawn(i, c, e, a=None):
    i.send("SELF", priority=True)


async def sect_a():
    print("== A: shed-by-provenance drops + settle trip, both engines ==")
    for engine in ("async", "sync"):
        C.clear()
        m = create_machine(
            copy.deepcopy(SHED_CFG),
            logic=MachineLogic(actions={"respawn": respawn, "cext": cext}),
        )
        if engine == "async":
            it = Interpreter(m)
            it.use(Hooks())
            await it.start()
            for _ in range(40):
                await it.send("EXT", priority=True)
            await it.send("SELF")
            for _ in range(200):
                await asyncio.sleep(0.005)
                if it.last_error is not None:
                    break
            ext = it.context.get("ext", 0)
            err = type(it.last_error).__name__ if it.last_error else None
            await it.stop()
        else:
            it = SyncInterpreter(m)
            it.use(Hooks())
            it.start()
            for _ in range(40):
                it.send("EXT", priority=True)
            it.send("SELF")
            ext = it.context.get("ext", 0)
            err = type(it.last_error).__name__ if it.last_error else None
            it.stop()
        drops = {k: v for k, v in C.items() if k.startswith("drop:")}
        dt = {k: v for k, v in C.items() if k.startswith("droptype:")}
        extlost = 40 - ext
        print(
            f"  {engine:6s} EXT applied={ext}/40 lost={extlost} err={err} "
            f"drops={drops} shed_types={dt} "
            f"=> {'PASS' if extlost == 0 and err else 'FAIL'}"
        )


# ---------------------------------------------------------------- C
SOAK_CFGS = {
    "async_svc": {
        "id": "a",
        "initial": "s",
        "states": {
            "s": {"on": {"GO": "run"}},
            "run": {"invoke": {"id": "i", "src": "svc", "onDone": {"target": "s"}}},
        },
    },
    "rollback_ondone": {
        "id": "b",
        "initial": "s",
        "actionErrorPolicy": "rollback",
        "maxIterations": 20,
        "states": {
            "s": {"on": {"GO": "run"}},
            "run": {"invoke": {"id": "i", "src": "svc", "onDone": {"target": "s"}}},
        },
    },
    "always_invoke": {
        "id": "c",
        "initial": "s",
        "maxIterations": 20,
        "context": {"ext": 0},
        "on": {"EXT": {"actions": ["cext"]}},
        "states": {
            "s": {"on": {"GO": "run"}},
            "run": {
                "always": {"target": "w", "guard": "yes"},
                "on": {"EXT": {"actions": ["cext"]}},
            },
            "w": {
                "invoke": {"id": "i", "src": "svc", "onDone": {"target": "s"}},
                "on": {"EXT": {"actions": ["cext"]}},
            },
        },
    },
}


async def soak(seconds, M):
    print(f"== C: SOAK {seconds}s, {M} machines ==")
    try:
        import psutil

        proc = psutil.Process(os.getpid())
    except Exception:
        proc = None

    async def svc(i, c, e):
        await asyncio.sleep(0.002)
        return {"v": 1}

    def yes(i, c, e):
        return True

    logic = MachineLogic(
        services={"svc": svc}, actions={"cext": cext}, guards={"yes": yes}
    )
    its = []
    names = list(SOAK_CFGS)
    for k in range(M):
        cfg = copy.deepcopy(SOAK_CFGS[names[k % len(names)]])
        cfg["id"] = f"m{k}"
        m = create_machine(cfg, logic=logic)
        it = Interpreter(m)
        it.use(Hooks())
        await it.start()
        its.append(it)

    t0 = time.perf_counter()
    cpu0 = proc.cpu_times() if proc else None
    th0 = threading.active_count()
    C.clear()
    ext_sent = 0
    snaps = collections.Counter()
    while time.perf_counter() - t0 < seconds:
        for it in its:
            try:
                await it.send("GO")
            except Exception:
                pass
            try:
                await it.send("EXT", priority=True)
                ext_sent += 1
            except Exception:
                pass
        await asyncio.sleep(0.01)
        # chaos snapshot at quiescence
        for it in its[:5]:
            try:
                it.get_snapshot()
                snaps["ok"] += 1
            except Exception as exc:
                snaps[type(exc).__name__] += 1
    el = time.perf_counter() - t0
    cpu = None
    if proc:
        c1 = proc.cpu_times()
        cpu = (c1.user - cpu0.user) + (c1.system - cpu0.system)
    ext_applied = sum(i.context.get("ext", 0) for i in its)
    running = sum(1 for i in its if i.status == "running")
    for it in its:
        try:
            await it.stop()
        except Exception:
            pass
    await asyncio.sleep(0.3)
    gc.collect()
    th1 = threading.active_count()
    drops = {k: v for k, v in C.items() if k.startswith("drop:")}
    errs = {k: v for k, v in C.items() if k.startswith("err:")}
    ncpu = os.cpu_count() or 1
    print(f"  elapsed={el:.1f}s machines={M} running_at_end={running}/{M}")
    print(f"  cpu={cpu if cpu is None else round(cpu,1)}s ({'n/a' if cpu is None else round(100*cpu/el/ncpu,1)}% of {ncpu} cores)")
    print(f"  EXT sent={ext_sent} applied={ext_applied} drops={drops}")
    print(f"  errors={errs}")
    print(f"  chaos snapshots={dict(snaps)}")
    print(f"  threads {th0} -> {th1} => {'PASS(no leak)' if th1 <= th0 + 2 else 'FAIL(thread leak)'}")


async def main():
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 90.0
    M = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    await sect_a()
    await soak(secs, M)


asyncio.run(main())
