# -*- coding: utf-8 -*-
"""B18 KillSwitch: happy path, cancel/flatten branches, INV-B18-a..e,
send_priority preemption of a busy inbox, onUnhandled=error, snapshots."""
import asyncio, json
from xstate_statemachine import Interpreter, OverflowPolicy
from xstate_statemachine.clock import SimulatedClock
from charness import Stub, TraceP, build, ids, SETTLE
from cdrv import (mk, step, cfg_of, run_plain, run_snapshotted, compare,
                  run_sync_parity)

R = {}

G_ENGAGE_ONLY = {"cancel_working_requested": False, "flatten_requested": False,
                 "all_accounts_flat": False, "owner_and_elevated": True,
                 "owner_and_elevated_and_acknowledged_residual": True}
G_FULL = {"cancel_working_requested": True, "flatten_requested": True,
          "all_accounts_flat": True, "owner_and_elevated": True,
          "owner_and_elevated_and_acknowledged_residual": True}
G_PARTIAL = dict(G_FULL, all_accounts_flat=False)


async def _slow():
    await asyncio.sleep(0.05)
    return {"ok": True}


async def _long(i, c, e):
    await asyncio.sleep(0.4)
    return {"ok": True}


async def priority_probe():
    """Busy inbox: a long invoke runs and N events queue behind it.
    send_priority must jump them and answer with bounded latency."""
    cfg = cfg_of("B18")
    st = Stub(cfg, guard_vals=G_FULL,
              svc={"cancel_all_working_orders": _long,
                   "flatten_all_positions": _long})
    m = build(cfg, st)
    clock = SimulatedClock()
    interp = Interpreter(m, clock=clock, max_queue_size=64,
                         overflow_policy=OverflowPolicy.RAISE)
    tp = TraceP()
    interp.use(tp)
    await interp.start()
    await asyncio.sleep(SETTLE)
    await interp.send("ENGAGE", wait=False)
    await asyncio.sleep(0.05)
    busy_ids = sorted(interp.current_state_ids)
    for _ in range(20):
        await interp.send("RETRY_FLATTEN", wait=False)
    qd = getattr(interp, "queue_depth", None)
    loop = asyncio.get_event_loop()
    t0 = loop.time()
    try:
        rec = await asyncio.wait_for(interp.send_priority("RELEASE"),
                                     timeout=3.0)
        out = {"busy_ids": busy_ids, "queue_depth": qd,
               "priority_latency_s": round(loop.time() - t0, 4),
               "changed": rec.changed,
               "error": type(rec.error).__name__ if rec.error else None,
               "err": str(rec.error)[:160] if rec.error else None,
               "ids_after": sorted(interp.current_state_ids),
               "status": interp.status}
    except Exception as e:  # noqa: BLE001
        out = {"busy_ids": busy_ids, "queue_depth": qd,
               "priority": "%s: %s" % (type(e).__name__, str(e)[:200]),
               "elapsed": round(loop.time() - t0, 3),
               "status": interp.status,
               "ids_after": sorted(interp.current_state_ids)}
    await asyncio.sleep(0.8)
    out["final_ids"] = sorted(interp.current_state_ids)
    out["unhandled"] = tp.unhandled[:5]
    out["dropped"] = tp.dropped[:5]
    out["trace_tail"] = st.trace[-6:]
    try:
        await interp.stop()
    except Exception:
        pass
    return out


async def main():
    R["engage_only"] = await run_plain("B18", ["ENGAGE", "RELEASE"],
                                       {"guard_vals": G_ENGAGE_ONLY})
    R["full_flat"] = await run_plain("B18", ["ENGAGE", "RELEASE"],
                                     {"guard_vals": G_FULL})
    R["incomplete"] = await run_plain("B18", ["ENGAGE"],
                                      {"guard_vals": G_PARTIAL})
    R["incomplete_retry"] = await run_plain(
        "B18", ["ENGAGE", "RETRY_FLATTEN"], {"guard_vals": G_PARTIAL})
    R["cancel_error"] = await run_plain(
        "B18", ["ENGAGE"],
        {"guard_vals": G_FULL,
         "svc": {"cancel_all_working_orders": RuntimeError("cx down")}})
    R["flatten_error"] = await run_plain(
        "B18", ["ENGAGE"],
        {"guard_vals": G_FULL,
         "svc": {"flatten_all_positions": RuntimeError("fl down")}})
    R["release_denied"] = await run_plain(
        "B18", ["ENGAGE", "RELEASE"],
        {"guard_vals": dict(G_ENGAGE_ONLY, owner_and_elevated=False)})
    R["release_incomplete_denied"] = await run_plain(
        "B18", ["ENGAGE", "RELEASE"],
        {"guard_vals": dict(
            G_PARTIAL, owner_and_elevated_and_acknowledged_residual=False)})

    # INV-B18-a/b: the block flag is set on ENTRY to engaging, observable
    # at the caller before the macrostep finishes settling.
    cfg = cfg_of("B18")
    flag = {"blocked": False}

    def block_impl(interp, ctx, evt, ad):
        flag["blocked"] = True

    st = Stub(cfg, guard_vals=G_FULL,
              act_impl={"block_new_orders_immediately": block_impl},
              svc={"cancel_all_working_orders": lambda i, c, e: _slow(),
                   "flatten_all_positions": lambda i, c, e: _slow()})
    m = build(cfg, st)
    clock = SimulatedClock()
    interp = Interpreter(m, clock=clock, max_queue_size=8,
                         overflow_policy=OverflowPolicy.RAISE)
    tp = TraceP()
    interp.use(tp)
    await interp.start()
    await asyncio.sleep(SETTLE)
    await interp.send("ENGAGE", wait=True)
    R["inv_b18b"] = {"blocked_at_receipt": flag["blocked"],
                     "ids_at_receipt": sorted(interp.current_state_ids),
                     "trace": list(st.trace)}
    await asyncio.sleep(0.4)
    R["inv_b18b"]["final_ids"] = sorted(interp.current_state_ids)
    await interp.stop()

    R["priority"] = await priority_probe()

    # onUnhandled: "error" -- RELEASE is not handled in `clear`.
    interp, st, tp, clock, m = await mk("B18", {"guard_vals": G_ENGAGE_ONLY})
    try:
        r = await step(interp, clock, "RELEASE")
        R["unhandled_error"] = {
            "changed": r.changed,
            "error": type(r.error).__name__ if r.error else None,
            "err": str(r.error)[:200] if r.error else None,
            "status": interp.status,
            "ids": sorted(interp.current_state_ids),
            "unhandled": list(tp.unhandled)}
    except Exception as e:  # noqa: BLE001
        R["unhandled_error"] = "RAISED %s: %s" % (type(e).__name__, str(e)[:200])
    try:
        await interp.stop()
    except Exception:
        pass

    for nm, seq, gv in [("engage_only", ["ENGAGE", "RELEASE"], G_ENGAGE_ONLY),
                        ("full", ["ENGAGE", "RELEASE"], G_FULL),
                        ("incomplete", ["ENGAGE", "RETRY_FLATTEN"], G_PARTIAL)]:
        plain = await run_plain("B18", seq, {"guard_vals": gv})
        try:
            snap = await run_snapshotted("B18", seq, {"guard_vals": gv})
            R["snap_" + nm] = {"midstep_errors": snap["midstep_errors"],
                               "diffs": compare(plain, snap),
                               "plain_acts": plain["acts"],
                               "snap_acts": snap["acts"],
                               "plain_ids": plain["ids"],
                               "ids": snap["ids"]}
        except Exception as e:  # noqa: BLE001
            R["snap_" + nm] = "RAISED %s: %s" % (type(e).__name__, str(e)[:300])

    R["sync_parity_full"] = run_sync_parity("B18", ["ENGAGE", "RELEASE"],
                                            {"guard_vals": G_FULL})


asyncio.run(main())
json.dump(R, open("results/c3_b18.json", "w", encoding="utf-8"),
          indent=2, default=str)
for k, v in R.items():
    print(k, "=", json.dumps(v, default=str)[:700])
    print()
