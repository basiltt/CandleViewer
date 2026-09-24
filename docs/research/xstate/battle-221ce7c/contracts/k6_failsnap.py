# -*- coding: utf-8 -*-
"""Does a 'fail'-stopped snapshot restore as a live machine? (MUST-01)"""
import asyncio, json
from cdrv import cfg_of
from charness import Stub, ids, SETTLE
from xstate_statemachine import Interpreter, OverflowPolicy, create_machine
from xstate_statemachine.clock import SimulatedClock

R = {}
async def main():
    cfg = cfg_of("B17"); cfg["actionErrorPolicy"] = "fail"
    st = Stub(cfg, guard_vals={"all_evidence_present": True,
                               "owner_and_elevated_and_evidence_still_valid": True},
              raising=["audit_live_enabled"])
    m = create_machine(json.loads(json.dumps(cfg)), logic=st.logic())
    it = Interpreter(m, clock=SimulatedClock(), max_queue_size=64,
                     overflow_policy=OverflowPolicy.RAISE)
    await it.start(); await asyncio.sleep(SETTLE)
    await it.send("EVIDENCE_RECORDED", wait=True)
    await it.send("ENABLE_REQUESTED", wait=True)
    await asyncio.sleep(SETTLE)
    blob = json.dumps(it.get_persisted_snapshot())
    R["persisted_status"] = json.loads(blob).get("status")
    R["persisted_config"] = json.loads(blob).get("configuration")
    try: await it.stop()
    except Exception: pass
    try:
        it2 = Interpreter.from_snapshot(blob, m, clock=SimulatedClock())
        await it2.start(); await asyncio.sleep(SETTLE)
        R["restored"] = {"status": it2.status, "ids": ids(it2),
                         "is_running": getattr(it2, "is_running", None)}
        try:
            r = await asyncio.wait_for(it2.send("EVIDENCE_RECORDED", wait=True), 3)
            R["restored"]["accepts_events"] = {"changed": r.changed,
                "error": type(r.error).__name__ if r.error else None}
        except Exception as e:
            R["restored"]["accepts_events"] = f"{type(e).__name__}: {str(e)[:140]}"
        try: await it2.stop()
        except Exception: pass
    except Exception as e:
        R["restored"] = f"{type(e).__name__}: {str(e)[:200]}"

asyncio.run(main())
json.dump(R, open("results/k6_failsnap.json", "w", encoding="utf-8"), indent=2, default=str)
print(json.dumps(R, indent=1, default=str))
