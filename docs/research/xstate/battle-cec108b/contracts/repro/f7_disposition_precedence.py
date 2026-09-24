# -*- coding: utf-8 -*-
"""#153's `guard_denied` disposition vs onUnhandled:"defer". The catalogue
mandates defer on the order path. Which disposition wins?"""
import asyncio, json, copy, cvlib
from cvlib import Rig

async def run(policy):
    cfg = copy.deepcopy(cvlib.load("B8")); cfg["onUnhandled"] = policy
    rig = Rig(guard_values={"exchange_reports_sl": True, "tightens_only": False})
    _m, it, plug, clock = cvlib.new_interp(cfg, rig)
    await it.start(); await asyncio.sleep(0.05)
    await it.send("POSITION_OPENED"); await asyncio.sleep(0.2)
    plug.unhandled.clear()
    err = None
    try:
        r = await it.send("TIGHTEN_SL", wait=True)
        rec = {"changed": r.changed, "deferred": r.deferred, "denied": r.denied}
    except Exception as e:
        err = f"{type(e).__name__}"; rec = None
    await asyncio.sleep(0.05)
    out = {"onUnhandled": policy, "dispositions": plug.unhandled,
           "receipt": rec, "call_raised": err}
    await it.stop(); return out

async def main():
    res = [await run(p) for p in ("defer", "ignore", "error")]
    print(json.dumps(res, indent=1))
    json.dump(res, open("repro/f7_disposition_precedence.json","w"), indent=1)

asyncio.run(main())
