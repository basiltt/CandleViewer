# -*- coding: utf-8 -*-
"""Step 1 - create_machine with stub MachineLogic for B16..B20."""
import json, sys, traceback
from charness import Stub, build, collect

BS = ["B16", "B17", "B18", "B19", "B20"]
out = {}
for b in BS:
    cfg = json.load(open(f"{b}.catalogue.json", encoding="utf-8"))
    acts, guards, svcs, delays, evts = collect(cfg)
    rec = {"actions": acts, "guards": guards, "services": svcs,
           "delays": delays, "events": evts}
    # 1a: bare MachineLogic -> expect ImplementationMissingError
    from xstate_statemachine import MachineLogic, create_machine
    try:
        create_machine(cfg, logic=MachineLogic())
        rec["bare"] = "BUILD OK (no impls required?!)"
    except Exception as e:
        rec["bare"] = f"{type(e).__name__}: {str(e)[:200]}"
    # 1b: full stub
    try:
        st = Stub(cfg)
        m = build(cfg, st)
        rec["stub"] = "BUILD OK"
        rec["root_type"] = cfg.get("type", "compound")
        rec["policies"] = {k: cfg.get(k) for k in
                           ("actionErrorPolicy", "onUnhandled",
                            "guardErrorPolicy", "strictTargets", "strict",
                            "spawnBlockingTimeout")}
        rec["policy_seen"] = {
            "action_error_policy": getattr(m, "action_error_policy", "<absent>"),
            "unhandled_policy": getattr(m, "unhandled_policy", "<absent>"),
            "guard_error_policy": getattr(m, "guard_error_policy", "<absent>"),
            "spawn_blocking_timeout_ms": getattr(m, "spawn_blocking_timeout_ms", "<absent>"),
        }
    except Exception as e:
        rec["stub"] = f"{type(e).__name__}: {str(e)[:400]}"
        traceback.print_exc()
    out[b] = rec
print(json.dumps(out, indent=2))
json.dump(out, open("results/c0_build.json", "w", encoding="utf-8"), indent=2)
