# -*- coding: utf-8 -*-
"""m1: the CV-221-01 hazard on f28719c -- rollback + invoke.onDone + raising
action at the target, on the REAL B18/B19 and on a 4-state minimal repro,
for BOTH service kinds (def / async def).

STANDALONE: stdlib + xstate_statemachine only.
Self-bounded: every cell is a fixed observation window.
"""
from __future__ import annotations
import asyncio, json, pathlib, time
from xstate_statemachine import (Interpreter, MachineLogic, OverflowPolicy,
                                 create_machine)
from xstate_statemachine.actions import is_builtin
from xstate_statemachine.clock import SimulatedClock

HERE = pathlib.Path(__file__).parent
R = {}


# ---------------------------------------------------------------- helpers --
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


class Counters:
    def __init__(self):
        self.svc = 0
        self.acts = 0
        self.trace = []


def mklogic(cfg, style, guard_vals, raising, C):
    a, g, s = collect(cfg)

    def mk_a(n):
        def f(interp, ctx, evt, ad):
            C.acts += 1
            if len(C.trace) < 400:
                C.trace.append(n)
            if n in raising:
                raise RuntimeError("boom:" + n)
        f.__name__ = n
        return f

    def mk_g(n):
        def gg(ctx, evt):
            return bool(guard_vals.get(n, False))
        gg.__name__ = n
        return gg

    def mk_s(n):
        if style == "async":
            async def s_(interp, ctx, evt):
                C.svc += 1
                return {"ok": True}
        else:
            def s_(interp, ctx, evt):
                C.svc += 1
                return {"ok": True}
        s_.__name__ = n
        return s_

    return MachineLogic(
        actions={n: mk_a(n) for n in a
                 if not is_builtin(n) and not n.startswith("spawn_")},
        guards={n: mk_g(n) for n in g},
        services={n: mk_s(n) for n in s},
        strict=True)


async def cell(cfg, style, event, guard_vals, raising, windows=(1.0, 2.0),
               max_iterations=None, payload=None):
    C = Counters()
    c = json.loads(json.dumps(cfg))
    if max_iterations is not None:
        c["maxIterations"] = max_iterations
    m = create_machine(c, logic=mklogic(c, style, guard_vals, raising, C),
                       strict_targets=c.get("strictTargets", True))
    i = Interpreter(m, clock=SimulatedClock(), max_queue_size=256,
                    overflow_policy=OverflowPolicy.RAISE)
    await i.start()
    await asyncio.sleep(0.05)
    t0 = time.perf_counter()
    try:
        rec = await asyncio.wait_for(
            i.send(event, wait=True, **(payload or {})), 3.0)
        receipt = {"changed": getattr(rec, "changed", None),
                   "error": repr(getattr(rec, "error", None))}
    except asyncio.TimeoutError:
        receipt = {"timeout": True}
    except Exception as e:
        receipt = {"exc": repr(e)}
    samples = []
    for w in windows:
        while time.perf_counter() - t0 < w:
            await asyncio.sleep(0.02)
        samples.append({"t": w, "svc": C.svc, "acts": C.acts})
    out = {"style": style, "receipt": receipt, "samples": samples,
           "growing": samples[-1]["svc"] > samples[0]["svc"] + 2,
           "states": sorted(i.current_state_ids), "status": i.status,
           "last_error": repr(i.last_error),
           "declared_max_iterations": getattr(m, "max_iterations", None),
           "trace_head": C.trace[:12]}
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception as e:
        out["stop"] = repr(e)
    return out


MIN = {
    "id": "m", "initial": "idle", "actionErrorPolicy": "rollback",
    "guardErrorPolicy": "raise", "strict": True, "strictTargets": True,
    "context": {},
    "states": {
        "idle": {"on": {"GO": "a"}},
        "a": {"invoke": {"id": "s", "src": "svc",
                         "onDone": {"target": "#m.c"},
                         "onError": {"target": "#m.c"}}},
        "c": {"entry": ["boom"]},
    },
}


async def main():
    cfg18 = json.loads((HERE / "B18.machine.json").read_text(encoding="utf-8"))
    cfg19 = json.loads((HERE / "B19.machine.json").read_text(encoding="utf-8"))

    # --- minimal repro, both kinds, several budgets -----------------------
    for style in ("async", "def"):
        for mi in (None, 5, 50):
            k = "min/%s/maxIter=%s" % (style, mi)
            R[k] = await cell(MIN, style, "GO", {}, {"boom"},
                              max_iterations=mi)
            print(k, R[k]["samples"], R[k]["last_error"][:60], flush=True)

    # --- ablations (async lane only; the lane that was unbounded) ---------
    import copy
    ab = copy.deepcopy(MIN); ab["actionErrorPolicy"] = "continue"
    R["min/ablate/continue"] = await cell(ab, "async", "GO", {}, {"boom"})
    ab2 = copy.deepcopy(MIN); ab2["actionErrorPolicy"] = "fail"
    R["min/ablate/fail"] = await cell(ab2, "async", "GO", {}, {"boom"})
    R["min/ablate/no-raise"] = await cell(MIN, "async", "GO", {}, set())
    for k in ("min/ablate/continue", "min/ablate/fail", "min/ablate/no-raise"):
        print(k, R[k]["samples"], R[k]["states"], R[k]["status"], flush=True)

    # --- B18: the incident-day configuration ------------------------------
    gv18 = {"cancel_working_requested": True, "flatten_requested": True,
            "all_accounts_flat": False, "owner_and_elevated": True}
    for style in ("async", "def"):
        for mi in (None, 5):
            k = "B18/%s/maxIter=%s" % (style, mi)
            R[k] = await cell(cfg18, style, "ENGAGE", gv18, {"page_owner"},
                              max_iterations=mi)
            print(k, R[k]["samples"], R[k]["states"],
                  R[k]["last_error"][:60], flush=True)
    # B18 control: nothing raises
    R["B18/control"] = await cell(cfg18, "async", "ENGAGE", gv18, set())
    print("B18/control", R["B18/control"]["samples"],
          R["B18/control"]["states"], flush=True)
    # B18 rollback BEFORE any invoke is armed
    R["B18/rollback-pre-invoke"] = await cell(
        cfg18, "async", "ENGAGE", gv18, {"block_new_orders_immediately"})
    print("B18/rollback-pre-invoke", R["B18/rollback-pre-invoke"]["samples"],
          R["B18/rollback-pre-invoke"]["states"],
          R["B18/rollback-pre-invoke"]["receipt"], flush=True)

    # --- B19: two hazard sites -------------------------------------------
    gv19 = {"divergences_found_and_auto_remediate": True,
            "unresolved_divergences": True, "failures_exhausted": False}
    for style in ("async", "def"):
        R["B19/%s/onDone-action" % style] = await cell(
            cfg19, style, "SWEEP_DUE", gv19, {"store_divergences"})
        R["B19/%s/always-entry" % style] = await cell(
            cfg19, style, "SWEEP_DUE", gv19, {"persist_report"})
        for s in ("onDone-action", "always-entry"):
            k = "B19/%s/%s" % (style, s)
            print(k, R[k]["samples"], R[k]["states"],
                  R[k]["last_error"][:60], flush=True)
    R["B19/control"] = await cell(cfg19, "async", "SWEEP_DUE", gv19, set())
    print("B19/control", R["B19/control"]["samples"],
          R["B19/control"]["states"], flush=True)


asyncio.run(main())
(HERE / "results").mkdir(exist_ok=True)
(HERE / "results" / "m1_hazard.json").write_text(
    json.dumps(R, indent=2, default=str), encoding="utf-8")
print("\nwrote results/m1_hazard.json")
