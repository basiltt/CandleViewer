# -*- coding: utf-8 -*-
"""LD-01 re-test on cec108b (#152 guardErrorPolicy raise per-candidate,
#153 Receipt.denied). Where does a raising guard surface, per path?"""
import asyncio, json, cvlib
from cvlib import Rig

async def caller_wait():
    cfg = cvlib.load("B8")
    rig = Rig(guard_values={"exchange_reports_sl": True},
              guard_raises={"tightens_only"})
    _m, it, plug, clock = cvlib.new_interp(cfg, rig)
    await it.start(); await asyncio.sleep(0.05)
    await it.send("POSITION_OPENED"); await asyncio.sleep(0.15)
    pre = sorted(it.current_state_ids)
    raised = "NO-RAISE"
    try:
        r = await it.send("TIGHTEN_SL", wait=True)
        rec = {"changed": r.changed, "deferred": r.deferred, "denied": r.denied,
               "error": type(r.error).__name__ if r.error else None}
    except Exception as e:
        raised = f"{type(e).__name__}: {str(e)[:100]}"; rec = None
    await asyncio.sleep(0.05)
    out = {"path": "send(wait=True)", "pre": pre, "call_raised": raised,
           "receipt": rec, "states": sorted(it.current_state_ids),
           "status": it.status, "interp_error": repr(getattr(it,"error",None)),
           "last_transition_ok": getattr(it,"last_transition_ok",None),
           "last_error": repr(getattr(it,"last_error",None))}
    await it.stop(); return out

async def fire_forget():
    cfg = cvlib.load("B8")
    rig = Rig(guard_values={"exchange_reports_sl": True},
              guard_raises={"tightens_only"})
    _m, it, plug, clock = cvlib.new_interp(cfg, rig)
    await it.start(); await asyncio.sleep(0.05)
    await it.send("POSITION_OPENED"); await asyncio.sleep(0.15)
    await it.send("TIGHTEN_SL"); await asyncio.sleep(0.15)
    out = {"path": "send() fire-and-forget", "states": sorted(it.current_state_ids),
           "status": it.status, "interp_error": repr(getattr(it,"error",None)),
           "last_transition_ok": getattr(it,"last_transition_ok",None),
           "last_error": repr(getattr(it,"last_error",None)),
           "dropped": plug.dropped, "unhandled": getattr(plug,"unhandled",None)}
    await it.stop(); return out

async def invoke_ondone():
    """The B8 strand: guard on read_position_sl's onDone raises.
    #152 says the fallback (unguarded) candidate must now be taken."""
    cfg = cvlib.load("B8")
    rig = Rig(guard_raises={"exchange_reports_sl"})
    _m, it, plug, clock = cvlib.new_interp(cfg, rig)
    await it.start(); await asyncio.sleep(0.05)
    await it.send("POSITION_OPENED"); await asyncio.sleep(0.4)
    stuck = sorted(it.current_state_ids)
    for ev in ("SCAN_DUE","SL_DEADLINE","TIGHTEN_SL","POSITION_OPENED"):
        try: await it.send(ev)
        except Exception: pass
    await asyncio.sleep(0.3)
    try: pend = [repr(p)[:120] for p in it.pending_invocations()]
    except Exception as e: pend = f"{type(e).__name__}"
    out = {"path": "guard on invoke.onDone", "after_invoke": stuck,
           "after_pokes": sorted(it.current_state_ids), "status": it.status,
           "interp_error": repr(getattr(it,"error",None)),
           "last_transition_ok": getattr(it,"last_transition_ok",None),
           "last_error": repr(getattr(it,"last_error",None))[:160],
           "deferred_count": it.deferred_count,
           "pending_invocations": pend,
           "fallback_taken_naked": any("naked" in s for s in it.current_state_ids)}
    await it.stop(); return out

async def main():
    res = [await caller_wait(), await fire_forget(), await invoke_ondone()]
    print(json.dumps(res, indent=1))
    json.dump(res, open("repro/f4_guard_raise_sinks.json","w"), indent=1)

asyncio.run(main())
