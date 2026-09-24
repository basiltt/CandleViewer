# -*- coding: utf-8 -*-
"""Sync-engine parity (informational): same script, SyncInterpreter."""
from __future__ import annotations
import json
from xstate_statemachine import SyncInterpreter
from xstate_statemachine.clock import SimulatedClock
import charness as H

OUT = {}
SCRIPTS = {
    "B1": (["VALIDATE", "SEND", "EXEC", "FIRST_FILL", "SL_OBSERVED"],
           dict(guard_vals={"passes_all_gates": True, "ret_code_ok": True,
                            "exec_new_and_partial": True},
                svc={"place_order": {"retCode": 0}, "attach_native_sl": {"ok": True}})),
    "B2": (["CONFIRM", "LEG_OPEN", "LEG_OPEN", "ALL_LEGS_FLAT"],
           dict(guard_vals={"all_non_skipped_open":
                            lambda c, e: c["legs_open"] >= 2},
                act_impl={"count_open": lambda i, c, e, a:
                          c.__setitem__("legs_open", c["legs_open"] + 1)})),
    "B3": (["ORDER_OPEN", "EXEC", "CLOSE"],
           dict(guard_vals={"should_skip": False, "passes_preflight": True,
                            "fully_filled": False})),
    "B4": (["LEG_A_FILL", "CHILDREN_TERMINAL"],
           dict(guard_vals={"position_overshoots": False, "other_leg_terminal": True},
                svc={"submit_both_legs": {}, "settle_other_leg": {}})),
    "B5": (["CHILD_FILLED", "REFILL_DUE"],
           dict(guard_vals={"preflight_invalid": False, "remaining_is_zero": False,
                            "slices_exhausted": False},
                svc={"submit_child": {"id": "c1"}})),
}

for b, (script, kw) in SCRIPTS.items():
    cfg = json.load(open(b + ".machine.json", encoding="utf-8"))
    st = H.Stub(cfg, **kw)
    try:
        i = SyncInterpreter(H.build(cfg, st))
        i.start()
        for ev in script:
            try:
                i.send(ev)
            except Exception as e:
                pass
        ids = sorted(i.current_state_ids)
        i.stop()
        OUT[b] = {"ok": True, "ids": ids, "trace": st.trace}
    except Exception as e:
        OUT[b] = {"ok": False, "err": "%s: %s" % (type(e).__name__, str(e)[:160])}
    print(b, OUT[b].get("ids") or OUT[b].get("err"))

json.dump(OUT, open("sync_parity.json", "w", encoding="utf-8"), indent=1)
