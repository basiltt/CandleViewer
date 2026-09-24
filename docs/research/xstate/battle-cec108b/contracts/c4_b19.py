# -*- coding: utf-8 -*-
"""B19 Reconciliation: pipeline, divergence paths, reconnect/resync,
stale_lockout, CANCEL-mid-fetch (no stale done.invoke), snapshot parity."""
import asyncio, json
from cdrv import (mk, step, cfg_of, run_plain, run_snapshotted, compare,
                  run_sync_parity)
from charness import Stub, TraceP, build, SETTLE
from xstate_statemachine import Interpreter, create_machine
from xstate_statemachine.clock import SimulatedClock

R = {}

G_CLEAN = {"failures_exhausted": False,
           "divergences_found_and_auto_remediate": False,
           "unresolved_divergences": False}
G_DIVERGE = dict(G_CLEAN, divergences_found_and_auto_remediate=True)
G_UNRESOLVED = dict(G_DIVERGE, unresolved_divergences=True)


async def main():
    # ---- happy path: sweep with no divergence -------------------------
    R["clean_sweep"] = await run_plain("B19", ["SWEEP_DUE"],
                                       {"guard_vals": G_CLEAN})
    # ---- divergence found -> remediate -> report -> idle --------------
    R["remediated"] = await run_plain("B19", ["SWEEP_DUE"],
                                      {"guard_vals": G_DIVERGE})
    # ---- divergence unresolved -> divergent (needs_attention) ---------
    R["divergent"] = await run_plain("B19", ["SWEEP_DUE"],
                                     {"guard_vals": G_UNRESOLVED})
    R["divergent_resolved"] = await run_plain(
        "B19", ["SWEEP_DUE", "OPERATOR_RESOLVED"],
        {"guard_vals": G_UNRESOLVED})
    # ---- INV-B19-c/e: reconnect/resync sequence -----------------------
    R["reconnect"] = await run_plain("B19", ["RECONNECTED"],
                                     {"guard_vals": G_CLEAN})
    R["unknown_order"] = await run_plain("B19", ["UNKNOWN_ORDER"],
                                         {"guard_vals": G_CLEAN})
    R["startup"] = await run_plain("B19", ["STARTUP"], {"guard_vals": G_CLEAN})
    # ---- fetch fails -> backing_off -> RETRY_DUE ----------------------
    R["backoff"] = await run_plain(
        "B19", ["SWEEP_DUE", "RETRY_DUE"],
        {"guard_vals": G_CLEAN,
         "svc": {"fetch_exchange_state": RuntimeError("exchange 503")}})
    # ---- failures exhausted -> stale_lockout --------------------------
    R["stale_lockout"] = await run_plain(
        "B19", ["SWEEP_DUE"],
        {"guard_vals": dict(G_CLEAN, failures_exhausted=True),
         "svc": {"fetch_exchange_state": RuntimeError("exchange 503")}})
    # INV-B19-b: cleared only by ... contract says OPERATOR_RESOLVED but
    # the JSON only handles RECONNECTED in stale_lockout.
    R["stale_lockout_reconnect"] = await run_plain(
        "B19", ["SWEEP_DUE", "RECONNECTED"],
        {"guard_vals": dict(G_CLEAN, failures_exhausted=True),
         "svc": {"fetch_exchange_state": RuntimeError("exchange 503")}})
    try:
        R["stale_lockout_operator"] = await run_plain(
            "B19", ["SWEEP_DUE", "OPERATOR_RESOLVED"],
            {"guard_vals": dict(G_CLEAN, failures_exhausted=True),
             "svc": {"fetch_exchange_state": RuntimeError("exchange 503")}})
    except Exception as e:  # noqa: BLE001
        R["stale_lockout_operator"] = "%s: %s" % (type(e).__name__, str(e)[:200])
    # ---- diff / remediate error branches ------------------------------
    R["diff_error"] = await run_plain(
        "B19", ["SWEEP_DUE"],
        {"guard_vals": G_CLEAN,
         "svc": {"diff_against_local": RuntimeError("diff boom")}})
    R["remediate_error"] = await run_plain(
        "B19", ["SWEEP_DUE"],
        {"guard_vals": G_DIVERGE,
         "svc": {"apply_remediations": RuntimeError("rem boom")}})

    # ---- CANCEL a mid-flight sweep: no stale done.invoke later --------
    R["cancel_midflight"] = await cancel_midflight()

    # ---- deferral while fetching: an event arriving mid-sweep ---------
    R["defer_during_fetch"] = await defer_during_fetch()

    # ---- snapshots between every macrostep ----------------------------
    for nm, seq, gv in [("clean", ["SWEEP_DUE", "SWEEP_DUE"], G_CLEAN),
                        ("divergent", ["SWEEP_DUE", "OPERATOR_RESOLVED"],
                         G_UNRESOLVED),
                        ("remediate", ["SWEEP_DUE"], G_DIVERGE)]:
        plain = await run_plain("B19", seq, {"guard_vals": gv})
        try:
            snap = await run_snapshotted("B19", seq, {"guard_vals": gv})
            R["snap_" + nm] = {"midstep_errors": snap["midstep_errors"],
                               "diffs": compare(plain, snap),
                               "plain_acts": plain["acts"],
                               "snap_acts": snap["acts"],
                               "plain_ids": plain["ids"], "ids": snap["ids"]}
        except Exception as e:  # noqa: BLE001
            R["snap_" + nm] = "RAISED %s: %s" % (type(e).__name__, str(e)[:300])

    # ---- INV-B19-e: static restore of a machine parked mid-fetch ------
    R["parked_midfetch"] = await parked_midfetch()

    R["sync_parity"] = run_sync_parity("B19", ["SWEEP_DUE"],
                                       {"guard_vals": G_CLEAN})


async def _slow_fetch(interp, ctx, evt):
    await asyncio.sleep(0.4)
    return {"orders": []}


def _mk(bn, guard_vals, slow=None, **ikw):
    cfg = cfg_of(bn)
    st = Stub(cfg, guard_vals=guard_vals)
    logic = st.logic()
    if slow:
        for k, v in slow.items():
            logic.services[k] = v
    m = create_machine(cfg, logic=logic, strict_targets=True)
    clock = SimulatedClock()
    interp = Interpreter(m, clock=clock, **ikw)
    tp = TraceP()
    interp.use(tp)
    return interp, st, tp, clock, m


async def cancel_midflight():
    interp, st, tp, clock, m = _mk(
        "B19", G_CLEAN, slow={"fetch_exchange_state": _slow_fetch})
    await interp.start()
    await asyncio.sleep(SETTLE)
    await interp.send("SWEEP_DUE", wait=False)
    await asyncio.sleep(0.08)
    mid = sorted(interp.current_state_ids)
    r = await interp.send("CANCEL", wait=True)
    await asyncio.sleep(0.05)
    right_after = sorted(interp.current_state_ids)
    await asyncio.sleep(0.7)            # long past when the fetch would end
    out = {"mid_ids": mid, "cancel_changed": r.changed,
           "cancel_deferred": getattr(r, "deferred", None),
           "ids_after_cancel": right_after,
           "ids_later": sorted(interp.current_state_ids),
           "transitions": list(tp.transitions),
           "acts": list(st.trace),
           "status": interp.status}
    await interp.stop()
    return out


async def defer_during_fetch():
    interp, st, tp, clock, m = _mk(
        "B19", G_CLEAN, slow={"fetch_exchange_state": _slow_fetch})
    await interp.start()
    await asyncio.sleep(SETTLE)
    await interp.send("SWEEP_DUE", wait=False)
    await asyncio.sleep(0.08)
    # UNKNOWN_ORDER has no handler in `fetching` (only the inline `*` defer,
    # which under onUnhandled:"defer" should never be consulted).
    r = await interp.send("UNKNOWN_ORDER", wait=True)
    out = {"mid_ids": sorted(interp.current_state_ids),
           "receipt": {"changed": r.changed, "deferred": getattr(r, "deferred", None)},
           "deferred_count": interp.deferred_count,
           "acts_at_receipt": list(st.trace),
           "unhandled": list(tp.unhandled)}
    await asyncio.sleep(0.9)
    out["ids_later"] = sorted(interp.current_state_ids)
    out["acts_later"] = list(st.trace)
    out["transitions"] = list(tp.transitions)
    out["deferred_later"] = interp.deferred_count
    await interp.stop()
    return out


async def parked_midfetch():
    """Snapshot while `fetching` is occupied -> restore -> is it inert?"""
    interp, st, tp, clock, m = _mk(
        "B19", G_CLEAN, slow={"fetch_exchange_state": _slow_fetch})
    await interp.start()
    await asyncio.sleep(SETTLE)
    await interp.send("SWEEP_DUE", wait=False)
    await asyncio.sleep(0.08)
    out = {"ids_at_snapshot": sorted(interp.current_state_ids)}
    try:
        blob = json.dumps(interp.get_persisted_snapshot())
        out["snapshot"] = "OK"
    except Exception as e:  # noqa: BLE001
        out["snapshot"] = "%s: %s" % (type(e).__name__, str(e)[:200])
        await interp.stop()
        return out
    await interp.stop()
    for flag in (False, True):
        clock2 = SimulatedClock()
        r2 = Interpreter.from_snapshot(blob, m, clock=clock2,
                                       restart_services=flag,
                                       restart_timers=flag)
        rec = {"status_before_start": r2.status,
               "has_dormant_invocations": getattr(r2, "has_dormant_invocations", "<absent>"),
               "has_dormant_timers": getattr(r2, "has_dormant_timers", "<absent>"),
               "pending_invocations": [str(p) for p in
                                       (r2.pending_invocations() or [])][:4]}
        await r2.start()
        await asyncio.sleep(0.8)
        rec["ids_after_start"] = sorted(r2.current_state_ids)
        rec["status_after"] = r2.status
        await r2.stop()
        out["restart_services=%s" % flag] = rec
    return out


asyncio.run(main())
json.dump(R, open("results/c4_b19.json", "w", encoding="utf-8"),
          indent=2, default=str)
for k, v in R.items():
    print(k, "=", json.dumps(v, default=str)[:650])
    print()
