"""R4 -- persistence property on 6db65d8's NEW machinery (#182/#183/#187):
`get_persisted_snapshot()` from EVERY hook must be refused-or-legal, never
torn -- including the INITIAL DESCENT (#182) and an invoked CHILD's entry
actions (#183), on BOTH engines and with BOTH service kinds.

A produced blob is TORN when its `context["n"]` disagrees with the
`context["committed"]` watermark the action writes after the probe, i.e. the
snapshot captured a half-applied action list; or when it fails to round-trip.

Usage: r4_persist_property.py [N]
"""
import asyncio, copy, json, logging, random, sys, warnings
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
from xstate_statemachine import (
    Interpreter,
    SyncInterpreter,
    MachineLogic,
    PluginBase,
    create_machine,
)
from xstate_statemachine.exceptions import (
    SnapshotCorruptError,
    SnapshotMidStepError,
)

RES = {"refused": 0, "produced": 0, "torn": 0, "untyped": {}, "sites": {}}
TORN = []


def probe(it, site):
    s = RES["sites"].setdefault(
        site, {"refused": 0, "produced": 0, "torn": 0}
    )
    try:
        blob = it.get_persisted_snapshot()
    except (SnapshotMidStepError, SnapshotCorruptError):
        RES["refused"] += 1
        s["refused"] += 1
        return
    except Exception as e:
        RES["untyped"][f"{site}:{type(e).__name__}"] = str(e)[:90]
        return
    RES["produced"] += 1
    s["produced"] += 1
    d = blob if isinstance(blob, dict) else json.loads(blob)
    try:
        json.dumps(d)
    except Exception as e:
        RES["untyped"][f"{site}:dumps:{type(e).__name__}"] = str(e)[:90]
        return
    ctx = d.get("context") or {}
    n, c = ctx.get("n"), ctx.get("committed")
    if isinstance(n, int) and c is not None and n != c:
        RES["torn"] += 1
        s["torn"] += 1
        TORN.append((site, n, c))


def gen(rnd, i):
    """Random chart: 30% parallel, 30% with an invoked CHILD machine, rest
    nested.  Every one has entry/exit actions in the initial descent."""
    kind = rnd.random()
    child = {
        "id": f"kid{i}",
        "initial": "k0",
        "states": {
            "k0": {"entry": ["mark"], "on": {"GO": "k1"}},
            "k1": {"entry": ["mark"], "type": "final"},
        },
    }
    if kind < 0.30:
        return {
            "id": f"m{i}",
            "type": "parallel",
            "states": {
                "r0": {
                    "initial": "s0",
                    "states": {
                        "s0": {"entry": ["mark"], "on": {"GO": "s1"}},
                        "s1": {
                            "entry": ["mark"],
                            "exit": ["mark"],
                            "initial": "x",
                            "states": {"x": {"entry": ["mark"]}},
                        },
                    },
                },
                "r1": {
                    "initial": "t0",
                    "states": {
                        "t0": {"on": {"GO": {"target": "t1", "actions": ["mark"]}}},
                        "t1": {"entry": ["mark"]},
                    },
                },
            },
        }, None
    if kind < 0.60:
        # invoked CHILD machine in the INITIAL entry set -> #182 + #183
        return {
            "id": f"m{i}",
            "initial": "a",
            "states": {
                "a": {
                    "entry": ["mark"],
                    "invoke": {"id": "kid", "src": "kidmachine"},
                    "on": {"GO": {"target": "b", "actions": ["mark"]}},
                },
                "b": {"entry": ["mark"]},
            },
        }, child
    return {
        "id": f"m{i}",
        "initial": "a",
        "states": {
            "a": {
                "entry": ["mark"],
                "exit": ["mark"],
                "invoke": {"id": "inv", "src": "svc"},
                "on": {"GO": {"target": "b", "guard": "g", "actions": ["mark"]}},
            },
            "b": {
                "entry": ["mark"],
                "initial": "c",
                "states": {
                    "c": {"entry": ["mark"], "on": {"GO": "d"}},
                    "d": {"entry": ["mark"]},
                },
            },
        },
    }, None


class P(PluginBase):
    def on_transition(self, interp, f, t, ev):
        probe(interp, "on_transition")


def make_logic(async_svc: bool, childmachine):
    def mark(i, c, e, a):
        if isinstance(c, dict):
            c["n"] = c.get("n", 0) + 1
            probe(i, "action")  # mid-action-list: context half-applied
            c["committed"] = c["n"]

    def g(c, e):
        probe_it = getattr(g, "it", None)
        if probe_it is not None:
            probe(probe_it, "guard")
        return True

    if async_svc:

        async def svc(i, c, e):
            await asyncio.sleep(0)
            return {"ok": 1}

    else:

        def svc(i, c, e):
            return {"ok": 1}

    services = {"svc": svc}
    if childmachine is not None:
        services["kidmachine"] = create_machine(
            copy.deepcopy(childmachine),
            logic=MachineLogic(actions={"mark": mark}),
        )
    return MachineLogic(actions={"mark": mark}, guards={"g": g}, services=services), g


def run_sync(cfg, child, async_svc):
    logic, g = make_logic(async_svc, child)
    it = SyncInterpreter(create_machine(copy.deepcopy(cfg), logic=logic))
    g.it = it
    it.use(P())
    it.start()
    for ev in ("GO", "GO"):
        try:
            it.send(ev)
        except Exception:
            pass
    it.stop()


async def run_async(cfg, child, async_svc):
    logic, g = make_logic(async_svc, child)
    it = Interpreter(create_machine(copy.deepcopy(cfg), logic=logic))
    g.it = it
    it.use(P())
    try:
        await asyncio.wait_for(it.start(children_timeout=1.0), 8)
    except asyncio.TimeoutError:
        return
    for ev in ("GO", "GO"):
        try:
            await asyncio.wait_for(it.send(ev, wait=True), 5)
        except Exception:
            pass
    try:
        await asyncio.wait_for(it.stop(), 5)
    except Exception:
        pass


async def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    rnd = random.Random(90210)
    per = {}
    for i in range(n):
        cfg, child = gen(rnd, i)
        for async_svc in (False, True):
            before = dict(RES)
            try:
                run_sync(cfg, child, async_svc)
            except Exception as e:
                RES["untyped"][f"sync_setup:{type(e).__name__}"] = str(e)[:90]
            try:
                await run_async(cfg, child, async_svc)
            except Exception as e:
                RES["untyped"][f"async_setup:{type(e).__name__}"] = str(e)[:90]
            k = "async def" if async_svc else "plain def"
            p = per.setdefault(k, {"refused": 0, "produced": 0, "torn": 0})
            for f in p:
                p[f] += RES[f] - before[f]
        if (i + 1) % 100 == 0:
            print(f"  ...{i+1}/{n} {RES['refused']=} {RES['produced']=} {RES['torn']=}")
    print(f"\nmachines={n} (each run on BOTH engines x BOTH service kinds)")
    print(f"  refused={RES['refused']}  produced={RES['produced']}  TORN={RES['torn']}")
    print(f"  untyped={RES['untyped']}")
    for site, s in sorted(RES["sites"].items()):
        print(f"  site {site:<14} refused={s['refused']:>6} produced={s['produced']:>5} torn={s['torn']:>4}")
    for k, p in per.items():
        print(f"  svc {k:<10} {p}")
    if TORN:
        print(f"  TORN SAMPLES: {TORN[:5]}")


asyncio.run(main())
