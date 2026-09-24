# -*- coding: utf-8 -*-
"""Sync-engine parity on the B6..B10 happy scripts, and the LD-INLINE
question on SyncInterpreter (where a plain service is the ONLY style).
"""
from __future__ import annotations
import asyncio, json, os, sys
os.environ["CV_SVC_STYLE"] = "def"
import cv6db as H
from cv6db import Stub

SCRIPTS = {
    "B6": (["SLICE_DUE", "SLICE_DUE", "DURATION_END", "CHILDREN_TERMINAL"],
           {"slice_qty_below_min_roll_forward": False,
            "price_limit_breached": False, "failures_exhausted": False,
            "preflight_invalid": False, "abort_on_price_limit": False,
            "final_market_sweep_and_remaining": False}),
    "B7": (["BOOK_TARGET_MOVED", "CHILD_FILLED", "CHILDREN_TERMINAL"],
           {"beyond_max_chase_ticks": False, "repricings_exhausted": False,
            "drift_over_threshold_and_interval_elapsed_and_budget_ok": True,
            "error_is_order_not_found_after_fill": False,
            "failures_exhausted": False, "on_timeout_is_market": False,
            "on_timeout_is_cancel": False}),
    "B8": (["POSITION_OPENED", "SCAN_DUE"],
           {"attach_attempts_left": True, "exchange_reports_sl": True,
            "tightens_only": True, "explicit_audited_override": False,
            "sl_observed": True}),
    "B9": (["SAVE", "ARM_REQUESTED", "TRIGGER", "COOLDOWN_DUE"],
           {"promotion_gate_satisfied_and_permitted": True,
            "debounce_blocked": False, "data_stale": False,
            "limits_blocked": False,
            "condition_true_and_requires_confirmation": False,
            "condition_true": True, "error_budget_exhausted": False,
            "once_satisfied": False}),
    "B10": (["CONDITION_MET", "ACK", "RESOLVE"],
            {"in_storm_window": False, "all_channels_ok": True,
             "delivery_attempts_left": True}),
}


async def main():
    rows = {}
    for b, (script, g) in SCRIPTS.items():
        c = H.cfg(b)
        a = await H.drive(c, Stub(c, guard_vals=dict(g), svc_style="def"),
                          list(script), snapshots=False)
        try:
            s = H.drive_sync(c, Stub(c, guard_vals=dict(g), sync=True),
                             list(script))
        except Exception as e:
            s = {"exc": repr(e)}
        rows[b] = {"async": {"states": a["states"], "actions": a["actions"],
                             "svc": a["svc_calls"]},
                   "sync": {"states": s.get("states"),
                            "actions": s.get("actions"),
                            "svc": s.get("svc_calls"), "exc": s.get("exc")}}
        H.rec("%s/sync parity: same final configuration" % b,
              a["states"] == s.get("states"),
              json.dumps({"async": a["states"], "sync": s.get("states")}))
        H.rec("%s/sync parity: same action trace" % b,
              a["actions"] == s.get("actions"),
              json.dumps({"async": a["actions"], "sync": s.get("actions")}))
        H.rec("%s/sync parity: same service calls" % b,
              a["svc_calls"] == s.get("svc_calls"),
              json.dumps({"async": a["svc_calls"], "sync": s.get("svc_calls")}))
    (H.HERE / "kd_parity_rows.json").write_text(json.dumps(rows, indent=1),
                                                encoding="utf-8")
    H.dump("kd_parity.json")

asyncio.run(main())
