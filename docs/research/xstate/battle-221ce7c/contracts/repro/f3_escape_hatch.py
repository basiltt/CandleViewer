# -*- coding: utf-8 -*-
"""Can POSITION_FLAT get the sl region out of the naked<->verifying cycle?
`naked` declares POSITION_FLAT -> flat. `verifying` does NOT (onUnhandled
defer holds it). Try repeatedly, and with send_priority."""
import asyncio, json, time, cvlib
from cvlib import Rig

async def attempt(mode, n=12):
    cfg = cvlib.load("B8")
    rig = Rig(guard_values={"exchange_reports_sl": False})
    _m, interp, plug, clock = cvlib.new_interp(cfg, rig)
    await interp.start(); await asyncio.sleep(0.05)
    await interp.send("POSITION_OPENED"); await asyncio.sleep(1.0)
    rs = []
    for _ in range(n):
        if mode == "priority":
            r = await interp.send_priority("POSITION_FLAT", wait=True)
        else:
            r = await interp.send("POSITION_FLAT", wait=True)
        rs.append({"changed": r.changed, "deferred": r.deferred,
                   "denied": r.denied, "ids": sorted(r.state_ids)})
        await asyncio.sleep(0.05)
        if sorted(interp.current_state_ids)[0].endswith("sl.flat"):
            break
    laps0 = rig.calls.count("S:attach_fallback_sl")
    await asyncio.sleep(0.8)
    out = {"mode": mode, "attempts": len(rs), "receipts": rs[:6],
           "final": sorted(interp.current_state_ids),
           "still_cycling": rig.calls.count("S:attach_fallback_sl") - laps0,
           "deferred_count": interp.deferred_count}
    await interp.stop()
    return out

async def main():
    res = [await attempt("normal"), await attempt("priority")]
    print(json.dumps(res, indent=1))
    json.dump(res, open("repro/f3_escape_hatch.json","w"), indent=1)

asyncio.run(main())
