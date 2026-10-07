# -*- coding: utf-8 -*-
"""B18 kill_switch: always -> invoked child, and send_priority under a
self-generated chain (0 dropped, kill preempts). Both service styles."""
from __future__ import annotations
import asyncio, json
import os, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cvf as K
os.chdir("<home>")

C = K.cfg("B18")


def s18(**kw):
    g = {"cancel_working_requested": lambda c, e: bool(c.get("cancel_working")),
         "flatten_requested": lambda c, e: bool(c.get("flatten")),
         "all_accounts_flat": True}
    g.update(kw.pop("guard_vals", {}) or {})
    a = {"record_engagement": lambda i, c, e, d: c.update(
        {"engaged_by": "op", "cancel_working": bool(
            getattr(e, "payload", {}).get("cancel_working")),
         "flatten": bool(getattr(e, "payload", {}).get("flatten"))})}
    a.update(kw.pop("act_impl", {}) or {})
    return K.Stub(C, guard_vals=g, act_impl=a, **kw)


async def main():
    # --- always -> invoked child: engaging.always -> cancelling(invoke) ----
    r = await K.drive(C, s18(), [("ENGAGE", {"cancel_working": True,
                                             "flatten": True})])
    K.rec("B18.always_to_invoke.svc_armed",
          "cancel_all_working_orders" in r["svc_calls"], str(r["svc_calls"]))
    K.rec("B18.always_to_invoke.chain_to_flatten",
          "flatten_all_positions" in r["svc_calls"], str(r["svc_calls"]))
    K.rec("B18.always_to_invoke.no_error", r["error"] is None, str(r["error"]))
    K.rec("B18.always_to_invoke.snapshot", r["snapshot_ok"],
          str(r["notes"])[:300])
    K.rec("B18.always_to_invoke.states", bool(r["states"]), str(r["states"]))
    json.dump(r, open("results/b18_always.%s.json" % K.STYLE, "w"),
              indent=1, default=str)
    print("  states=%s ctx_flat=%s" % (r["states"], r["context"].get("accounts_flat")))


if __name__ == "__main__":
    asyncio.run(main())
    K.dump("results/res_b18.json")
