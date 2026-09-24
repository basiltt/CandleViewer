# -*- coding: utf-8 -*-
"""Step 0: build B16-B20 from the round-5 corrected catalogue on cec108b."""
import json, pathlib, traceback
import charness
from charness import Stub, build, collect
from xstate_statemachine import MachineLogic, create_machine

R = {}
for b in ["B16", "B17", "B18", "B19", "B20"]:
    cfg = json.loads(pathlib.Path(b + ".catalogue.json").read_text(encoding="utf-8"))
    a, g, s, d, e = collect(cfg)
    row = {"id": cfg["id"], "root": cfg.get("type", "compound"),
           "policy": {k: cfg.get(k) for k in
                      ("actionErrorPolicy", "onUnhandled", "guardErrorPolicy",
                       "strictTargets", "strict", "spawnBlockingTimeout")},
           "n": {"actions": len(a), "guards": len(g), "services": len(s),
                 "delays": len(d), "events": len(e)},
           "events": e, "services": s,
           "has_halted": any("halt" in x for x in json.dumps(cfg)),
           }
    try:
        st = Stub(cfg); m = build(cfg, st)
        row["build_full_stub"] = "OK"
        row["machine_policy"] = {
            "action_error_policy": getattr(m, "action_error_policy", None),
            "guard_error_policy": getattr(m, "guard_error_policy", None),
            "on_unhandled": getattr(m, "on_unhandled", None),
            "spawn_blocking_timeout_ms": getattr(m, "spawn_blocking_timeout_ms", None),
        }
    except Exception as ex:
        row["build_full_stub"] = f"{type(ex).__name__}: {str(ex)[:200]}"
    try:
        create_machine(json.loads(json.dumps(cfg)), logic=MachineLogic())
        row["build_bare_logic"] = "OK"
    except Exception as ex:
        row["build_bare_logic"] = f"{type(ex).__name__}: {str(ex)[:160]}"
    # halted states present?
    def leaves(node, pre=""):
        out = []
        for k, v in (node.get("states") or {}).items():
            p = pre + "." + k
            out.append((p, v.get("type")))
            out += leaves(v, p)
        return out
    row["states"] = [p for p, t in leaves(cfg)]
    row["final_states"] = [p for p, t in leaves(cfg) if t == "final"]
    R[b] = row

json.dump(R, open("results/k0_build.json", "w", encoding="utf-8"), indent=2, default=str)
for b, r in R.items():
    print(b, r["id"], r["build_full_stub"], "| bare:", r["build_bare_logic"],
          "|", r["n"], "| halted:", any("halt" in s for s in r["states"]))
