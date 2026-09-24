# -*- coding: utf-8 -*-
"""A guard-DENIED event is also DEFERRED (onUnhandled:"defer"). On the
order path that means a business refusal is not a refusal -- it is stored
and replayed on the next configuration change. Does it ever drain? Does
it apply LATER, when the guard would answer differently?"""
import asyncio, json, cvlib
from cvlib import Rig

class Flip:
    """tightens_only False now, True after `flip()` -- a price moved."""
    def __init__(self): self.v = False
    def __call__(self, *a): return self.v

async def main():
    cfg = cvlib.load("B8")
    rig = Rig(guard_values={"exchange_reports_sl": True, "tightens_only": False,
                            "explicit_audited_override": False})
    _m, it, plug, clock = cvlib.new_interp(cfg, rig)
    await it.start(); await asyncio.sleep(0.05)
    await it.send("POSITION_OPENED"); await asyncio.sleep(0.2)
    steps = []
    # 3 denials in protected
    for i in range(3):
        r = await it.send("TIGHTEN_SL", wait=True); await asyncio.sleep(0.03)
        steps.append({"n": i, "denied": r.denied, "deferred": r.deferred,
                      "deferred_count": it.deferred_count})
    # now the guard flips True -- would the STORED denials fire an amend?
    rig.guard_values["tightens_only"] = True
    amends_before = rig.calls.count("S:set_trading_stop")
    # force a configuration change so the defer buffer replays
    await it.send("WATCHDOG_MISS", wait=True); await asyncio.sleep(0.3)
    out = {"denial_steps": steps,
           "deferred_after_denials": steps[-1]["deferred_count"],
           "amends_before_flip": amends_before,
           "amends_after_replay": rig.calls.count("S:set_trading_stop"),
           "states": sorted(it.current_state_ids),
           "deferred_count_final": it.deferred_count,
           "unhandled": plug.unhandled[:8] if hasattr(plug,"unhandled") else None}
    await it.stop()
    print(json.dumps(out, indent=1))
    json.dump(out, open("repro/f6_denied_defer_buffer.json","w"), indent=1)

asyncio.run(main())
