# -*- coding: utf-8 -*-
"""Step 1 (B11-B15): create_machine from the catalogue JSON verbatim."""
import json, os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import g3_harness as H
import xstate_statemachine as X

POLICY = ["actionErrorPolicy", "onUnhandled", "guardErrorPolicy",
          "strictTargets", "strict", "spawnBlockingTimeout"]
out = {}
for b in ["B11", "B12", "B13", "B14", "B15"]:
    cfg = H.load(b)
    r = {"id": cfg["id"], "policy": {k: cfg.get(k) for k in POLICY}}
    try:
        X.create_machine(json.loads(json.dumps(cfg)))
        r["no_logic"] = "OK"
    except Exception as e:
        r["no_logic"] = "%s: %s" % (type(e).__name__, str(e)[:250])
    try:
        X.create_machine(json.loads(json.dumps(cfg)), logic=X.MachineLogic(strict=True))
        r["empty_strict_logic"] = "OK"
    except Exception as e:
        r["empty_strict_logic"] = "%s: %s" % (type(e).__name__, str(e)[:250])
    st = H.Stub(cfg)
    try:
        m = H.build(cfg, st)
        r["stub_logic"] = "OK"
        got = {}
        for k in POLICY:
            sn = "".join("_" + c.lower() if c.isupper() else c for c in k)
            for attr in (k, sn):
                if hasattr(m, attr):
                    got[attr] = getattr(m, attr)
        r["machine_attrs"] = got
        # do the policy keys actually reach the machine?
        r["policy_honoured"] = {
            "onUnhandled": got.get("on_unhandled", got.get("onUnhandled", "ABSENT")),
            "actionErrorPolicy": got.get("action_error_policy", "ABSENT"),
            "guardErrorPolicy": got.get("guard_error_policy", "ABSENT"),
            "spawnBlockingTimeout": got.get("spawn_blocking_timeout", "ABSENT"),
        }
    except Exception as e:
        r["stub_logic"] = "%s: %s" % (type(e).__name__, str(e)[:400])
        r["tb"] = traceback.format_exc()[-700:]
    out[b] = r
print(json.dumps(out, indent=1, default=str))
os.makedirs("results", exist_ok=True)
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "g3_build.json"), "w"), indent=1, default=str)
