# -*- coding: utf-8 -*-
"""Is WATCHDOG_MISS actually LOST under concurrency, or does the machine
re-heal (naked -> attach_fallback -> verifying -> protected) because
exchange_reports_sl is True? Count naked ENTRIES, not the final state."""
import asyncio, json, cvlib
from cvlib import Rig

async def run(n_miss, heal):
    cfg = cvlib.load("B8")
    rig = Rig(guard_values={"exchange_reports_sl": heal, "sl_observed": False})
    _m, it, plug, clock = cvlib.new_interp(cfg, rig, max_queue_size=256)
    await it.start(); await asyncio.sleep(0.05)
    await it.send("POSITION_OPENED"); await asyncio.sleep(0.2)
    base = (it.context.get("_trace") or []).count("stamp_naked_since")
    evs = []
    for _ in range(n_miss):
        evs += ["SCAN_DUE", "WATCHDOG_MISS"]
    await asyncio.gather(*[it.send(e) for e in evs])
    await asyncio.sleep(0.6)
    tr = it.context.get("_trace") or []
    out = {"heal_guard_exchange_reports_sl": heal, "misses_sent": n_miss,
           "naked_entries": tr.count("stamp_naked_since") - base,
           "critical_alerts": tr.count("raise_critical_alert") - base,
           "final": sorted(it.current_state_ids),
           "deferred": it.deferred_count, "status": it.status}
    await it.stop(); return out

async def main():
    res = [await run(8, True), await run(8, False), await run(1, True)]
    print(json.dumps(res, indent=1))
    json.dump(res, open("repro/f8_watchdog_miss_concurrency.json","w"), indent=1)

asyncio.run(main())
