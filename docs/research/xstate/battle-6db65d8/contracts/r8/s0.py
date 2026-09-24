# -*- coding: utf-8 -*-
"""s0: create_machine for B16-B20, both service kinds."""
import json
from h import Stub, build, collect, cfg_of
from xstate_statemachine import MachineLogic, create_machine

R = {}
for b in ["B16", "B17", "B18", "B19", "B20"]:
    cfg = cfg_of(b)
    a, g, s, d, e = collect(cfg)
    row = {"id": cfg["id"],
           "policy": {k: cfg.get(k) for k in
                      ("actionErrorPolicy", "onUnhandled", "guardErrorPolicy",
                       "strictTargets", "strict", "spawnBlockingTimeout")},
           "n": {"actions": len(a), "guards": len(g), "services": len(s),
                 "delays": len(d), "events": len(e)},
           "services": s, "events": e}
    for kind in ("async", "sync"):
        try:
            st = Stub(cfg, kind=kind); m = build(cfg, st)
            row["build_" + kind] = "OK"
            row["machine_policy"] = {
                "action_error_policy": getattr(m, "action_error_policy", None),
                "guard_error_policy": getattr(m, "guard_error_policy", None),
                "on_unhandled": getattr(m, "on_unhandled", None)}
        except Exception as ex:
            row["build_" + kind] = f"{type(ex).__name__}: {str(ex)[:200]}"
    try:
        create_machine(json.loads(json.dumps(cfg)), logic=MachineLogic())
        row["build_bare"] = "OK"
    except Exception as ex:
        row["build_bare"] = f"{type(ex).__name__}: {str(ex)[:160]}"
    R[b] = row
json.dump(R, open("results/s0.json", "w", encoding="utf-8"), indent=2, default=str)
for b, r in R.items():
    print(b, r["id"], "| async:", r["build_async"], "| sync:", r["build_sync"],
          "| bare:", r["build_bare"], "|", r["n"], "|", r["policy"])
