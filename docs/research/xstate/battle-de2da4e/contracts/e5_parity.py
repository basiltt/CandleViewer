# -*- coding: utf-8 -*-
"""q5 @ c78ce99 -- sync-engine parity for B6-B10: configuration, ACTION
trace and SERVICE-CALL trace must match the async engine on a happy script.

Run: e5_parity.py
"""
from __future__ import annotations
import asyncio, json, os, sys
os.environ["CV_SVC_STYLE"] = "def"      # the sync engine runs plain defs
import cvde as H
from cvde import Stub

rec = H.rec

G6 = {"slice_qty_below_min_roll_forward": False, "price_limit_breached": False,
      "failures_exhausted": False, "preflight_invalid": False,
      "abort_on_price_limit": False, "final_market_sweep_and_remaining": False,
      "on_disconnect_is_freeze": True}
G7 = {"repricing_budget_exhausted": False, "chase_timeout_reached": False,
      "failures_exhausted": False, "price_moved_beyond_limit": False}
# NB: `exchange_reports_sl` MUST be true for the happy path; with it false
# B8's `verifying -> naked -> (fallback) -> verifying` retry cycle is a
# contract-level livelock (see report, CD-B8).
G8 = {"exchange_reports_sl": True, "attach_attempts_left": True,
      "tightens_only": True, "explicit_audited_override": False,
      "position_still_open": True}
G9 = {"condition_true": True, "condition_true_and_requires_confirmation": False,
      "error_budget_exhausted": False, "in_cooldown": False,
      "promotion_gate_satisfied_and_permitted": True, "debounce_blocked": False,
      "data_stale": False, "limits_blocked": False,
      "simulation_window_elapsed": True, "budget_exhausted": False}
G10 = {"in_storm_window": False, "all_channels_ok": True,
       "delivery_attempts_left": True, "severity_requires_ack": False}

CASES = [
    ("B6", G6, ["SLICE_DUE", "SLICE_DUE", "DURATION_END", "CHILDREN_TERMINAL"]),
    ("B7", G7, ["REPRICE_DUE", "FILLED"]),
    ("B8", G8, ["POSITION_OPENED"]),
    ("B9", G9, ["SAVE", "ARM_REQUESTED", "TRIGGER"]),
    ("B10", G10, ["CONDITION_MET", "RESOLVE"]),
]


async def main():
    for bid, gv, script in CASES:
        c = H.cfg(bid)
        sa = Stub(c, guard_vals=dict(gv), svc_style="def")
        a = await H.drive(c, sa, list(script))
        ss = Stub(c, guard_vals=dict(gv), svc_style="def")
        s = H.drive_sync(c, ss, list(script))
        rec("%s/parity: configuration" % bid, a["states"] == s["states"],
            json.dumps({"async": a["states"], "sync": s["states"]}))
        rec("%s/parity: ACTION trace" % bid, sa.trace == ss.trace,
            json.dumps({"async": sa.trace, "sync": ss.trace}))
        rec("%s/parity: SERVICE-CALL trace" % bid,
            a["svc_calls"] == s["svc_calls"],
            json.dumps({"async": a["svc_calls"], "sync": s["svc_calls"]}))
        rec("%s/snapshot v3 round-trip clean at every quiescence" % bid,
            a["snapshot_ok"],
            json.dumps([n for n in a["notes"] if "v3" not in n])[:300])
    H.dump("e5_parity.json")


asyncio.run(main())
