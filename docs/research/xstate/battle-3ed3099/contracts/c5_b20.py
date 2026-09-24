# -*- coding: utf-8 -*-
"""B20 RiskLockout: band transitions, expiry modes, override, INV-B20-a..f,
snapshot parity (absolute-deadline honoured across restore)."""
import asyncio, json
from cdrv import (mk, step, cfg_of, run_plain, run_snapshotted, compare,
                  run_sync_parity)

R = {}

G_CLEAR = {"breaches_daily_loss_cap": False, "within_warning_band": False,
           "outside_warning_band": False, "until_mode_is_time_based": True,
           "owner_and_elevated_and_override_permitted": True}
G_WARN = dict(G_CLEAR, within_warning_band=True)
G_BREACH = dict(G_CLEAR, breaches_daily_loss_cap=True)


async def main():
    # ---- band walk: clear -> warning -> locked ------------------------
    band = {"mode": "none"}
    gv = {"breaches_daily_loss_cap": lambda c, e: band["mode"] == "breach",
          "within_warning_band": lambda c, e: band["mode"] == "warn",
          "outside_warning_band": lambda c, e: band["mode"] == "none",
          "until_mode_is_time_based": lambda c, e: True,
          "owner_and_elevated_and_override_permitted": lambda c, e: True}
    interp, st, tp, clock, m = await mk("B20", {"guard_vals": gv})
    walk = []
    for mode in ["none", "warn", "none", "warn", "breach"]:
        band["mode"] = mode
        r = await step(interp, clock, "PNL_UPDATE")
        walk.append({"mode": mode, "ids": sorted(interp.current_state_ids),
                     "changed": r.changed, "acts": list(st.trace)})
    R["band_walk"] = walk
    # ---- INV-B20-e: manual mode ignores expiry ------------------------
    R["band_walk_final_acts"] = list(st.trace)
    await interp.stop()

    R["cap_breach"] = await run_plain("B20", ["CAP_BREACH"],
                                      {"guard_vals": G_CLEAR})
    R["manual_lock"] = await run_plain("B20", ["MANUAL_LOCK"],
                                       {"guard_vals": G_CLEAR})
    # time-based expiry clears
    R["expiry_time_based"] = await run_plain(
        "B20", ["MANUAL_LOCK", "EXPIRY_DUE"], {"guard_vals": G_CLEAR})
    # manual mode: expiry ignored + logged
    R["expiry_manual_mode"] = await run_plain(
        "B20", ["MANUAL_LOCK", "EXPIRY_DUE"],
        {"guard_vals": dict(G_CLEAR, until_mode_is_time_based=False)})
    # override permitted / denied
    R["override_ok"] = await run_plain(
        "B20", ["MANUAL_LOCK", "OVERRIDE_REQUESTED"], {"guard_vals": G_CLEAR})
    R["override_denied"] = await run_plain(
        "B20", ["MANUAL_LOCK", "OVERRIDE_REQUESTED"],
        {"guard_vals": dict(
            G_CLEAR, owner_and_elevated_and_override_permitted=False)})

    # ---- INV-B20-c: deny-polarity under guardErrorPolicy "raise" ------
    interp, st, tp, clock, m = await mk(
        "B20", {"guard_vals": G_CLEAR,
                "guard_raise": {"breaches_daily_loss_cap"}})
    r = await step(interp, clock, "PNL_UPDATE")
    R["guard_raises"] = {"ids": sorted(interp.current_state_ids),
                         "changed": r.changed,
                         "error": type(r.error).__name__ if r.error else None,
                         "err": str(r.error)[:140] if r.error else None,
                         "status": interp.status, "acts": list(st.trace)}
    # after a raised guard, can the machine still be locked?
    try:
        r2 = await step(interp, clock, "MANUAL_LOCK")
        R["guard_raises"]["after_manual_lock"] = {
            "changed": r2.changed, "ids": sorted(interp.current_state_ids),
            "status": interp.status}
    except Exception as e:  # noqa: BLE001
        R["guard_raises"]["after_manual_lock"] = "%s: %s" % (
            type(e).__name__, str(e)[:160])
    try:
        await interp.stop()
    except Exception:
        pass

    # ---- actionErrorPolicy: "fail" on the locked entry list -----------
    for bad in ["halt_new_orders", "compute_until", "broadcast_lockout"]:
        interp, st, tp, clock, m = await mk(
            "B20", {"guard_vals": G_CLEAR, "raising": {bad}})
        r = await step(interp, clock, "MANUAL_LOCK")
        rec = {"ids": sorted(interp.current_state_ids),
               "status": interp.status, "changed": r.changed,
               "error": type(r.error).__name__ if r.error else None,
               "acts": list(st.trace)}
        try:
            rec["snapshot"] = bool(interp.get_persisted_snapshot())
        except Exception as e:  # noqa: BLE001
            rec["snapshot"] = "%s: %s" % (type(e).__name__, str(e)[:160])
        R["fail_" + bad] = rec
        try:
            await interp.stop()
        except Exception:
            pass

    # ---- snapshots between every macrostep ----------------------------
    for nm, seq, gvv in [
            ("lock_expire", ["MANUAL_LOCK", "EXPIRY_DUE"], G_CLEAR),
            ("lock_override", ["MANUAL_LOCK", "OVERRIDE_REQUESTED"], G_CLEAR),
            ("breach", ["PNL_UPDATE"], G_BREACH),
            ("warn", ["PNL_UPDATE", "PNL_UPDATE"], G_WARN)]:
        plain = await run_plain("B20", seq, {"guard_vals": gvv})
        try:
            snap = await run_snapshotted("B20", seq, {"guard_vals": gvv})
            R["snap_" + nm] = {"midstep_errors": snap["midstep_errors"],
                               "diffs": compare(plain, snap),
                               "plain_acts": plain["acts"],
                               "snap_acts": snap["acts"],
                               "plain_ids": plain["ids"], "ids": snap["ids"]}
        except Exception as e:  # noqa: BLE001
            R["snap_" + nm] = "RAISED %s: %s" % (type(e).__name__, str(e)[:300])

    R["sync_parity"] = run_sync_parity("B20", ["MANUAL_LOCK", "EXPIRY_DUE"],
                                       {"guard_vals": G_CLEAR})


asyncio.run(main())
json.dump(R, open("results/c5_b20.json", "w", encoding="utf-8"),
          indent=2, default=str)
for k, v in R.items():
    print(k, "=", json.dumps(v, default=str)[:700])
    print()
