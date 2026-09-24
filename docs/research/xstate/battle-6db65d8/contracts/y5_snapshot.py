# -*- coding: utf-8 -*-
"""Snapshot/restore of the real contracts at every quiescence, plus the
#185/#186 drift refusals, on both service styles."""
from __future__ import annotations
import asyncio, json, logging
import cv6db as K
from xstate_statemachine import Interpreter
from xstate_statemachine.clock import SimulatedClock

logging.disable(logging.CRITICAL)

SCRIPTS = {
    "B1": ["VALIDATE", "SEND", "FIRST_FILL", "EXEC"],
    "B2": ["CONFIRM", "LEG_OPEN", "LEG_OPEN"],
    "B3": ["ORDER_OPEN", "EXEC", "CLOSE"],
    "B4": ["LEG_A_FILL"],
    "B5": ["CHILD_FILLED", "REFILL_DUE"],
}


def gv(b):
    if b == "B1":
        return {"passes_all_gates": True, "ret_code_ok": True,
                "exec_new_and_partial": True}
    if b == "B2":
        return {"all_non_skipped_open": lambda c, e: c["legs_open"] >= 2}
    if b == "B3":
        return {"passes_preflight": True, "fully_filled": False,
                "flat_confirmed": True}
    if b == "B4":
        return {"other_leg_terminal": True}
    return {"on_disconnect_is_freeze": True}


async def corrupt_checks(b, style):
    """#185 null machine_hash on a versioned blob; #186 configuration that
    contradicts state_ids."""
    c = K.cfg(b)
    st = K.Stub(c, guard_vals=gv(b), svc_style=style)
    m, i, p = await K.new_async(c, st)
    blob = i.get_persisted_snapshot()
    if isinstance(blob, dict):
        blob = json.dumps(blob)
    await i.stop()
    d = json.loads(blob)
    out = {}

    def restore(payload, **kw):
        st2 = K.Stub(c, guard_vals=gv(b), svc_style=style)
        m2 = K.build(c, st2)
        try:
            Interpreter.from_snapshot(json.dumps(payload), m2,
                                      clock=SimulatedClock(), **kw)
            return "ACCEPTED"
        except Exception as e:
            return type(e).__name__

    out["version"] = d.get("version")
    out["has_hash"] = "machine_hash" in d
    d1 = json.loads(json.dumps(d)); d1["machine_hash"] = None
    out["null_hash"] = restore(d1)
    d2 = json.loads(json.dumps(d)); d2.pop("machine_hash", None)
    out["absent_hash"] = restore(d2)
    if "configuration" in d and "state_ids" in d:
        d3 = json.loads(json.dumps(d)); d3["configuration"] = []
        out["empty_configuration"] = restore(d3)
        d4 = json.loads(json.dumps(d)); d4["state_ids"] = ["m.nope"]
        out["contradicting_state_ids"] = restore(d4)
    else:
        out["configuration_keys"] = sorted(d.keys())
    return out


async def main():
    style = K.STYLE
    for b, script in SCRIPTS.items():
        c = K.cfg(b)
        st = K.Stub(c, guard_vals=gv(b), svc_style=style)
        r = await K.drive(c, st, script, snapshots=True)
        K.rec("%s.snap.roundtrip_every_quiescence" % b, r["snapshot_ok"],
              "states=%s notes=%s" % (r["states"], str(r["notes"])[:300]))
        cc = await corrupt_checks(b, style)
        K.rec("%s.snap.null_hash_refused" % b,
              cc["null_hash"] != "ACCEPTED", json.dumps(cc))
        if "empty_configuration" in cc:
            K.rec("%s.snap.config_disagreement_refused" % b,
                  cc["empty_configuration"] != "ACCEPTED"
                  and cc["contradicting_state_ids"] != "ACCEPTED",
                  json.dumps(cc))
    K.dump("res_y5.json")


asyncio.run(main())
