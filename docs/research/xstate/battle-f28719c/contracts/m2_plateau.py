# -*- coding: utf-8 -*-
"""m2: does the chain PLATEAU at maxIterations, in both service kinds?

m1 showed trips at maxIterations=5/50 but 'still growing' at the 1000 default
inside a 2 s window -- which is only 'has not reached the budget yet'. This
script walks a budget ladder and watches each cell until it stops moving (or a
hard cap), so the plateau value can be compared to the budget exactly.

STANDALONE: stdlib + xstate_statemachine only.
"""
from __future__ import annotations
import asyncio, json, pathlib, time
from xstate_statemachine import (Interpreter, MachineLogic, OverflowPolicy,
                                 create_machine)
from xstate_statemachine.actions import is_builtin
from xstate_statemachine.clock import SimulatedClock

HERE = pathlib.Path(__file__).parent
R = {}


def collect(c):
    acts, guards, svcs = set(), set(), set()

    def A(v):
        if isinstance(v, str):
            acts.add(v)
        elif isinstance(v, dict) and isinstance(v.get("type"), str):
            acts.add(v["type"])
        elif isinstance(v, list):
            for i in v:
                A(i)

    def G(v):
        if isinstance(v, str):
            guards.add(v)
        elif isinstance(v, dict):
            for k in ("and", "or", "not"):
                if k in v:
                    x = v[k]
                    for i in (x if isinstance(x, list) else [x]):
                        G(i)

    def T(v):
        if isinstance(v, list):
            for i in v:
                T(i)
        elif isinstance(v, dict):
            A(v.get("actions")); G(v.get("guard") or v.get("cond"))

    def walk(n):
        A(n.get("entry")); A(n.get("exit"))
        for v in (n.get("on") or {}).values():
            T(v)
        T(n.get("always"))
        for v in (n.get("after") or {}).values():
            T(v)
        i = n.get("invoke")
        if i:
            for x in (i if isinstance(i, list) else [i]):
                if isinstance(x.get("src"), str):
                    svcs.add(x["src"])
                T(x.get("onDone")); T(x.get("onError"))
        for s in (n.get("states") or {}).values():
            walk(s)

    walk(c)
    return sorted(acts), sorted(guards), sorted(svcs)


class C:
    def __init__(self):
        self.svc = 0


def mklogic(cfg, style, gv, raising, c):
    a, g, s = collect(cfg)

    def mk_a(n):
        def f(interp, ctx, evt, ad):
            if n in raising:
                raise RuntimeError("boom:" + n)
        f.__name__ = n
        return f

    def mk_g(n):
        def gg(ctx, evt):
            return bool(gv.get(n, False))
        gg.__name__ = n
        return gg

    def mk_s(n):
        if style == "async":
            async def s_(i_, ctx, evt):
                c.svc += 1
                return {"ok": True}
        else:
            def s_(i_, ctx, evt):
                c.svc += 1
                return {"ok": True}
        s_.__name__ = n
        return s_

    return MachineLogic(
        actions={n: mk_a(n) for n in a
                 if not is_builtin(n) and not n.startswith("spawn_")},
        guards={n: mk_g(n) for n in g},
        services={n: mk_s(n) for n in s}, strict=True)


async def plateau(cfg, style, event, gv, raising, mi, cap=20.0):
    """Watch until the service count is unchanged for 0.6 s, or *cap*."""
    c = C()
    cc = json.loads(json.dumps(cfg))
    if mi is not None:
        cc["maxIterations"] = mi
    m = create_machine(cc, logic=mklogic(cc, style, gv, raising, c),
                       strict_targets=cc.get("strictTargets", True))
    i = Interpreter(m, clock=SimulatedClock(), max_queue_size=256,
                    overflow_policy=OverflowPolicy.RAISE)
    await i.start()
    await asyncio.sleep(0.05)
    t0 = time.perf_counter()
    try:
        await asyncio.wait_for(i.send(event, wait=True), 3.0)
    except Exception:
        pass
    last, stable_since = -1, t0
    while time.perf_counter() - t0 < cap:
        await asyncio.sleep(0.05)
        if c.svc != last:
            last, stable_since = c.svc, time.perf_counter()
        elif time.perf_counter() - stable_since > 0.6:
            break
    out = {"style": style, "maxIterations": mi,
           "declared": getattr(m, "max_iterations", None),
           "plateau_svc": c.svc, "sec": round(time.perf_counter() - t0, 2),
           "settled": time.perf_counter() - t0 < cap,
           "states": sorted(i.current_state_ids), "status": i.status,
           "last_error": type(i.last_error).__name__ if i.last_error else None}
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception:
        pass
    return out


MIN = {"id": "m", "initial": "idle", "actionErrorPolicy": "rollback",
       "guardErrorPolicy": "raise", "strict": True, "strictTargets": True,
       "context": {},
       "states": {"idle": {"on": {"GO": "a"}},
                  "a": {"invoke": {"id": "s", "src": "svc",
                                   "onDone": {"target": "#m.c"},
                                   "onError": {"target": "#m.c"}}},
                  "c": {"entry": ["boom"]}}}


async def main():
    cfg18 = json.loads((HERE / "B18.machine.json").read_text(encoding="utf-8"))
    cfg19 = json.loads((HERE / "B19.machine.json").read_text(encoding="utf-8"))
    gv18 = {"cancel_working_requested": True, "flatten_requested": True,
            "all_accounts_flat": False}
    gv19 = {"divergences_found_and_auto_remediate": True,
            "unresolved_divergences": True, "failures_exhausted": False}

    ladder = [2, 5, 25, 100]
    for style in ("async", "def"):
        for mi in ladder:
            k = "min/%s/%s" % (style, mi)
            R[k] = await plateau(MIN, style, "GO", {}, {"boom"}, mi)
            print("%-16s plateau=%-6s settled=%-5s %s" % (
                k, R[k]["plateau_svc"], R[k]["settled"],
                R[k]["last_error"]), flush=True)
    for style in ("async", "def"):
        for mi in ladder:
            k = "B18/%s/%s" % (style, mi)
            R[k] = await plateau(cfg18, style, "ENGAGE", gv18,
                                 {"page_owner"}, mi)
            print("%-16s plateau=%-6s settled=%-5s %s | %s" % (
                k, R[k]["plateau_svc"], R[k]["settled"], R[k]["last_error"],
                ",".join(R[k]["states"])), flush=True)
    for style in ("async", "def"):
        for mi in (5, 25):
            k = "B19/%s/%s" % (style, mi)
            R[k] = await plateau(cfg19, style, "SWEEP_DUE", gv19,
                                 {"store_divergences"}, mi)
            print("%-16s plateau=%-6s settled=%-5s %s | %s" % (
                k, R[k]["plateau_svc"], R[k]["settled"], R[k]["last_error"],
                ",".join(R[k]["states"])), flush=True)


asyncio.run(main())
(HERE / "results").mkdir(exist_ok=True)
(HERE / "results" / "m2_plateau.json").write_text(
    json.dumps(R, indent=2, default=str), encoding="utf-8")
print("\nwrote results/m2_plateau.json")
