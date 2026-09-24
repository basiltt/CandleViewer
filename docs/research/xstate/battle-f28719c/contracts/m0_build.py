# -*- coding: utf-8 -*-
"""Step 0 on f28719c: build B16-B20 under the mandatory config + shape census.

STANDALONE: stdlib + xstate_statemachine only.
"""
import json, pathlib, sys
from xstate_statemachine import MachineLogic, create_machine
from xstate_statemachine.actions import is_builtin

HERE = pathlib.Path(__file__).parent


def collect(c):
    acts, guards, svcs, delays, evts = set(), set(), set(), set(), set()
    inv, alw, ondone = [0], [0], [0]

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
            A(v.get("actions"))
            G(v.get("guard") or v.get("cond"))

    def walk(n):
        A(n.get("entry")); A(n.get("exit"))
        for k, v in (n.get("on") or {}).items():
            evts.add(k); T(v)
        if n.get("always"):
            alw[0] += 1
        T(n.get("always"))
        for d, v in (n.get("after") or {}).items():
            if not str(d).lstrip("-").isdigit():
                delays.add(str(d))
            T(v)
        i = n.get("invoke")
        if i:
            for x in (i if isinstance(i, list) else [i]):
                inv[0] += 1
                if isinstance(x.get("src"), str):
                    svcs.add(x["src"])
                if x.get("onDone"):
                    ondone[0] += 1
                T(x.get("onDone")); T(x.get("onError"))
        for s in (n.get("states") or {}).values():
            walk(s)

    walk(c)
    return (sorted(acts), sorted(guards), sorted(svcs), sorted(delays),
            sorted(evts), inv[0], alw[0], ondone[0])


def stub_logic(c, style):
    a, g, s, d, e, _i, _w, _o = collect(c)

    def mk_a(n):
        def f(interp, ctx, evt, ad):
            return None
        f.__name__ = n
        return f

    def mk_g(n):
        def gg(ctx, evt):
            return False
        gg.__name__ = n
        return gg

    def mk_s(n):
        if style == "async":
            async def s_(interp, ctx, evt):
                return {"ok": True}
        else:
            def s_(interp, ctx, evt):
                return {"ok": True}
        s_.__name__ = n
        return s_

    return MachineLogic(
        actions={n: mk_a(n) for n in a
                 if not is_builtin(n) and not n.startswith("spawn_")},
        guards={n: mk_g(n) for n in g},
        services={n: mk_s(n) for n in s},
        delays={n: 1000 for n in d},
        strict=True,
    )


def leaves(node, pre=""):
    out = []
    for k, v in (node.get("states") or {}).items():
        p = pre + "." + k
        out.append((p, v.get("type")))
        out += leaves(v, p)
    return out


R = {}
for b in ["B16", "B17", "B18", "B19", "B20"]:
    cfg = json.loads((HERE / (b + ".machine.json")).read_text(encoding="utf-8"))
    a, g, s, d, e, ninv, nalw, ndone = collect(cfg)
    row = {"id": cfg["id"], "root": cfg.get("type", "compound"),
           "policy": {k: cfg.get(k) for k in
                      ("actionErrorPolicy", "onUnhandled", "guardErrorPolicy",
                       "strictTargets", "strict", "spawnBlockingTimeout")},
           "n": {"actions": len(a), "guards": len(g), "services": len(s),
                 "delays": len(d), "events": len(e), "invoke": ninv,
                 "always": nalw, "onDone": ndone},
           "events": e, "services": s}
    for style in ("async", "def"):
        try:
            m = create_machine(json.loads(json.dumps(cfg)),
                               logic=stub_logic(cfg, style),
                               strict_targets=cfg.get("strictTargets", True))
            row["build_" + style] = "OK"
            row["machine_policy"] = {
                "action_error_policy": getattr(m, "action_error_policy", None),
                "guard_error_policy": getattr(m, "guard_error_policy", None),
                "on_unhandled": getattr(m, "on_unhandled", None),
                "spawn_blocking_timeout_ms": getattr(
                    m, "spawn_blocking_timeout_ms", None),
            }
        except Exception as ex:
            row["build_" + style] = "%s: %s" % (type(ex).__name__, str(ex)[:200])
    try:
        create_machine(json.loads(json.dumps(cfg)), logic=MachineLogic())
        row["build_bare_logic"] = "OK"
    except Exception as ex:
        row["build_bare_logic"] = "%s: %s" % (type(ex).__name__, str(ex)[:160])
    row["states"] = [p for p, t in leaves(cfg)]
    row["final_states"] = [p for p, t in leaves(cfg) if t == "final"]
    row["has_halted_state"] = any("halt" in p for p in row["states"])
    R[b] = row

(HERE / "results").mkdir(exist_ok=True)
(HERE / "results" / "m0_build.json").write_text(
    json.dumps(R, indent=2, default=str), encoding="utf-8")
for b, r in R.items():
    print(b, r["id"], "async:", r["build_async"], "| def:", r["build_def"],
          "| bare:", r["build_bare_logic"], "|", r["n"],
          "| halted:", r["has_halted_state"])
