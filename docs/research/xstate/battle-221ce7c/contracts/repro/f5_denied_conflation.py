# -*- coding: utf-8 -*-
"""#153 Receipt.denied is meant to mean "a handler was declared and every
guard REFUSED". Does a guard that CRASHED under guardErrorPolicy:"raise"
also read denied=True? If so the two cases #153 exists to separate are
re-merged, and `denied` alone is not a safe discriminator."""
import asyncio, json, cvlib
from cvlib import Rig

async def case(name, **rigkw):
    cfg = cvlib.load("B8")
    rig = Rig(guard_values={"exchange_reports_sl": True, **rigkw.pop("gv", {})},
              **rigkw)
    _m, it, plug, clock = cvlib.new_interp(cfg, rig)
    await it.start(); await asyncio.sleep(0.05)
    await it.send("POSITION_OPENED"); await asyncio.sleep(0.2)
    r = await it.send("TIGHTEN_SL", wait=True); await asyncio.sleep(0.05)
    out = {"case": name, "changed": r.changed, "deferred": r.deferred,
           "denied": r.denied,
           "error": type(r.error).__name__ if r.error else None,
           "states": sorted(it.current_state_ids)}
    await it.stop(); return out

async def main():
    res = [
        await case("guard returns False (true denial)", gv={"tightens_only": False}),
        await case("guard RAISES (not a denial)", guard_raises={"tightens_only"}),
        await case("no handler declared: send POSITION_FLAT-in-flat style",
                   gv={"tightens_only": True}),
    ]
    print(json.dumps(res, indent=1))
    json.dump(res, open("repro/f5_denied_conflation.json","w"), indent=1)

asyncio.run(main())
