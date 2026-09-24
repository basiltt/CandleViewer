# -*- coding: utf-8 -*-
"""B8 naked <-> verifying invoke-mediated livelock.

naked.invoke(attach_fallback_sl).onDone -> verifying
verifying.invoke(read_position_sl).onDone[!exchange_reports_sl] -> naked
Both services succeed; the guard says the exchange still reports no SL.
Each lap is a separate macrostep driven by engine `done.invoke.*` events,
so no chain budget / maxIterations applies. Measure laps per wall second
and whether ANY documented signal fires.
"""
import asyncio, json, time, cvlib
from cvlib import Rig

BUDGET = 8.0

async def main():
    cfg = cvlib.load("B8")
    rig = Rig(guard_values={"exchange_reports_sl": False})
    _m, interp, plug, clock = cvlib.new_interp(cfg, rig)
    await interp.start(); await asyncio.sleep(0.05)
    await interp.send("POSITION_OPENED")
    t0 = time.monotonic()
    while time.monotonic() - t0 < BUDGET:
        await asyncio.sleep(0.2)
        if interp.status != "running":
            break
    el = time.monotonic() - t0
    laps = rig.calls.count("S:attach_fallback_sl")
    alerts = (interp.context.get("_trace") or []).count("raise_critical_alert")
    out = {
        "elapsed_s": round(el, 2),
        "laps_naked_to_verifying": laps,
        "laps_per_sec": round(laps / el, 1),
        "raise_critical_alert_count": alerts,
        "status": interp.status,
        "interpreter_error": repr(getattr(interp, "error", None)),
        "last_transition_ok": getattr(interp, "last_transition_ok", "<n/a>"),
        "last_error": repr(getattr(interp, "last_error", None)),
        "dropped": plug.dropped[:5] if hasattr(plug, "dropped") else None,
        "states": sorted(interp.current_state_ids),
    }
    # is the machine still responsive to the escape hatch?
    r = await interp.send("POSITION_FLAT", wait=True)
    await asyncio.sleep(0.15)
    out["after_POSITION_FLAT"] = sorted(interp.current_state_ids)
    out["flat_receipt"] = {"changed": r.changed, "deferred": r.deferred,
                           "denied": r.denied,
                           "error": type(r.error).__name__ if r.error else None}
    await interp.stop()
    print(json.dumps(out, indent=1))
    json.dump(out, open("repro/f2_naked_verify_livelock.json", "w"), indent=1)

asyncio.run(main())
