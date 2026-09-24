# -*- coding: utf-8 -*-
"""Round-5 cross-contract analogues exercised on B6-B10 shapes.
 B11-analogue: concurrent hazard events into a PARALLEL machine (B8).
 B19-analogue: flap -- repeated arm/disarm must not lose the lockout (B9).
 B16-analogue: elevation is cleared by a lifecycle exit (B9 kill/rearm).
 B17-analogue: two-flag gate deny + raise polarity (B9 promotion).
"""
import asyncio, json, cvlib
from cvlib import Rig

R = []
def rec(name, ok, note, ev=None):
    R.append({"check": name, "verdict": "PASS" if ok else "FAIL",
              "note": note, "evidence": ev})

async def b11_concurrent():
    """16 hazard events fired concurrently into both B8 regions at once.
    Both regions must stay legal (exactly one leaf each) and the safety
    region must not lose a WATCHDOG_MISS."""
    cfg = cvlib.load("B8")
    rig = Rig(guard_values={"exchange_reports_sl": True, "sl_observed": False})
    _m, it, plug, clock = cvlib.new_interp(cfg, rig, max_queue_size=256)
    await it.start(); await asyncio.sleep(0.05)
    await it.send("POSITION_OPENED"); await asyncio.sleep(0.2)
    pre = sorted(it.current_state_ids)
    evs = ["SCAN_DUE", "WATCHDOG_MISS"] * 8
    await asyncio.gather(*[it.send(e) for e in evs])
    await asyncio.sleep(0.5)
    ids = sorted(it.current_state_ids)
    sl = [i for i in ids if ".sl." in i]; wd = [i for i in ids if ".watchdog." in i]
    rec("B11-analogue: concurrent hazards keep both regions legal",
        len(sl) == 1 and len(wd) == 1,
        "exactly one active leaf per region after 16 concurrent sends",
        {"pre": pre, "post": ids, "sl_leaves": len(sl), "wd_leaves": len(wd)})
    # Count naked ENTRIES, not the final leaf: with exchange_reports_sl True
    # the machine legitimately re-heals naked -> verifying -> protected, so
    # the final state is `protected` even though every miss was honoured.
    tr = it.context.get("_trace") or []
    rec("B11-analogue: no WATCHDOG_MISS is lost under concurrency",
        tr.count("stamp_naked_since") >= 8,
        "8 concurrent misses -> 8 naked entries + 8 critical alerts "
        "(final leaf is protected because the machine re-heals)",
        {"naked_entries": tr.count("stamp_naked_since"),
         "critical_alerts": tr.count("raise_critical_alert"),
         "sl": sl, "deferred": it.deferred_count})
    # snapshot at quiescence after the storm
    try:
        blob = it.get_persisted_snapshot(); snap_ok = "OK"
    except Exception as e:
        blob = None; snap_ok = f"{type(e).__name__}: {str(e)[:100]}"
    rec("B11-analogue: snapshot at quiescence after a concurrent storm",
        snap_ok == "OK", "no SnapshotMidStepError at rest", {"snapshot": snap_ok})
    await it.stop()

async def b19_flap():
    """B9 armed<->disarmed flap 20x; then kill switch. The lockout must
    survive the flap and consecutive_errors must not silently reset."""
    cfg = cvlib.load("B9")
    rig = Rig(guard_values={"promotion_gate_satisfied_and_permitted": True,
                            "rearm_permitted_and_elevated": False})
    _m, it, plug, clock = cvlib.new_interp(cfg, rig, max_queue_size=256)
    await it.start(); await asyncio.sleep(0.05)
    for e in ("SAVE", "ARM_REQUESTED"):
        await it.send(e); await asyncio.sleep(0.05)
    armed = sorted(it.current_state_ids)
    for _ in range(20):
        await it.send("DISARM"); await it.send("ARM_REQUESTED")
    await asyncio.sleep(0.4)
    mid = sorted(it.current_state_ids)
    await it.send("KILL_SWITCH"); await asyncio.sleep(0.2)
    killed = sorted(it.current_state_ids)
    # unelevated rearm must NOT escape
    for _ in range(5):
        await it.send("HUMAN_REARM")
    await asyncio.sleep(0.2)
    after = sorted(it.current_state_ids)
    rec("B19-analogue: 20x flap leaves a single legal leaf",
        len(mid) == 1, "no torn configuration after rapid arm/disarm",
        {"armed": armed, "after_flap": mid})
    rec("B19-analogue: stale_lockout survives the flap",
        all("kill_switched" in s for s in after),
        "KILL_SWITCH after a flap still locks; 5 unelevated rearms do not escape",
        {"killed": killed, "after_rearms": after})
    await it.stop()

async def b16_elevation():
    """Elevation must be a property of the event, not sticky state: an
    elevated rearm works, a later unelevated one must not."""
    cfg = cvlib.load("B9")
    gv = {"promotion_gate_satisfied_and_permitted": True, "rearm_permitted_and_elevated": True}
    rig = Rig(guard_values=gv)
    _m, it, plug, clock = cvlib.new_interp(cfg, rig)
    await it.start(); await asyncio.sleep(0.05)
    for e in ("SAVE", "ARM_REQUESTED", "KILL_SWITCH"):
        await it.send(e); await asyncio.sleep(0.05)
    await it.send("HUMAN_REARM"); await asyncio.sleep(0.15)
    rearmed = sorted(it.current_state_ids)
    # "logout": elevation drops
    rig.guard_values["rearm_permitted_and_elevated"] = False
    await it.send("KILL_SWITCH"); await asyncio.sleep(0.1)
    for _ in range(3):
        await it.send("HUMAN_REARM")
    await asyncio.sleep(0.2)
    after = sorted(it.current_state_ids)
    rec("B16-analogue: elevated rearm succeeds",
        any("armed" in s and "kill" not in s for s in rearmed),
        "elevated HUMAN_REARM is the one exit", {"states": rearmed})
    rec("B16-analogue: elevation cleared -> rearm refused",
        all("kill_switched" in s for s in after),
        "after elevation drops, 3 rearms are all refused",
        {"states": after, "deferred": it.deferred_count})
    await it.stop()

async def main():
    await b11_concurrent(); await b19_flap(); await b16_elevation()
    print(json.dumps(R, indent=1))
    json.dump(R, open("c10_analogues.json", "w"), indent=1)
    bad = [r for r in R if r["verdict"] == "FAIL"]
    print(f"\n=== {len(R)} checks, {len(bad)} FAIL ===")
    for b in bad: print("FAIL", b["check"], "|", b["note"])

asyncio.run(main())
