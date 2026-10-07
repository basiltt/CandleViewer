# -*- coding: utf-8 -*-
"""V2: B2 TradeGroup / B3 Leg / B4 OCO / B5 Iceberg end-to-end on v0.9.0,
plus the #225 self-send provenance shape the OMS actually uses.

#225: an action that spawns a worker or hands out a receipt is EXTERNAL
traffic. Both supported shapes are exercised:
  (a) hand-out: `fut = asyncio.ensure_future(i.send(E, wait=True))` inside
      an action, awaited by nobody in-step;
  (b) spawned worker: a task created by an action that outlives it and
      later does a plain `i.send(E)` -- must be admitted as external.

STANDALONE: stdlib + xstate_statemachine only, neutral cwd.
"""
from __future__ import annotations
import asyncio, json, os, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cv9 as K  # noqa: E402
os.chdir("<home>")


async def chart(bid, script, guard_vals, tag):
    c = K.cfg(bid)
    st = K.Stub(c, guard_vals=guard_vals)
    r = await K.drive(c, st, script)
    K.rec("V2.%s.%s_runs" % (bid, tag), r["status"] in ("running", "done"),
          "states=%s status=%s" % (r["states"], r["status"]))
    K.rec("V2.%s.%s_snapshot_ok" % (bid, tag), r["snapshot_ok"],
          "; ".join(r["notes"])[:400])
    K.rec("V2.%s.%s_chain_trips_zero" % (bid, tag), r["chain_trips"] == 0,
          "chain_trips=%r lce=%s" % (r["chain_trips"], r["last_chain_error"]))
    K.rec("V2.%s.%s_no_stranded" % (bid, tag), not r["stranded"],
          "%r" % (r["stranded"][:3],))
    K.rec("V2.%s.%s_no_service_errors" % (bid, tag), not r["service_errors"],
          "%r" % (r["service_errors"][:3],))
    # sync parity on the same script
    s = K.drive_sync(c, K.Stub(c, guard_vals=guard_vals, sync=True), script)
    K.rec("V2.%s.%s_sync_parity" % (bid, tag), r["states"] == s["states"],
          "async=%s sync=%s" % (r["states"], s["states"]))
    return r


async def b225_handout():
    """#225(a): the documented hand-out idiom inside an action. The receipt
    is handed to `ensure_future` and the action then awaits again -- on
    <=0.8.x this flipped to a refusal."""
    c = K.cfg("B1")
    seen = {}

    def spawn(interp, ctx, evt, ad):
        async def worker():
            await asyncio.sleep(0.01)
            try:
                await interp.send("SEND")
                seen["worker_send"] = "ok"
            except Exception as e:
                seen["worker_send"] = repr(e)
        seen["task"] = asyncio.ensure_future(worker())

    st = K.Stub(c, guard_vals={"passes_all_gates": True},
                act_impl={"stamp_validated": spawn})
    m, i, p = await K.new_async(c, st)
    await K.send(i, "VALIDATE")
    await K.quiesce(i, 6)
    K.rec("V2.225.spawned_worker_send_admitted",
          seen.get("worker_send") == "ok",
          "worker_send=%r states=%s" % (seen.get("worker_send"), K.ids(i)))
    K.rec("V2.225.spawned_worker_no_chain_trip",
          getattr(i, "chain_trips", -1) == 0,
          "chain_trips=%r" % getattr(i, "chain_trips", None))
    await i.stop()


async def b225_wait_true_handout():
    """#225(b): `ensure_future(i.send(..., wait=True))` handed out from an
    action that then awaits again. Must NOT be refused."""
    c = K.cfg("B1")
    seen = {}

    def handout(interp, ctx, evt, ad):
        try:
            fut = asyncio.ensure_future(interp.send("SEND", wait=True))
            seen["handed"] = True
            seen["fut"] = fut
        except Exception as e:
            seen["handed"] = repr(e)

    st = K.Stub(c, guard_vals={"passes_all_gates": True},
                act_impl={"stamp_validated": handout})
    m, i, p = await K.new_async(c, st)
    await K.send(i, "VALIDATE")
    await K.quiesce(i, 6)
    K.rec("V2.225.wait_true_handout_not_refused", seen.get("handed") is True,
          "handed=%r" % (seen.get("handed"),))
    fut = seen.get("fut")
    if fut is not None:
        try:
            await asyncio.wait_for(fut, 3)
            K.rec("V2.225.wait_true_handout_resolves", True, "receipt awaited ok")
        except Exception as e:
            K.rec("V2.225.wait_true_handout_resolves", False, repr(e)[:200])
    await i.stop()


async def main():
    await chart("B2", ["OPEN", "LEG_OPENED"],
                {"all_legs_reported": True, "any_leg_open": True,
                 "policy_all_or_none": False, "all_legs_open": True}, "happy")
    await chart("B3", [], {"should_skip": False, "passes_preflight": True},
                "preflight_ok")
    await chart("B4", ["FILL_A"],
                {"is_full_fill": True, "mode_is_reduce": False,
                 "both_filled": False, "within_tolerance": True}, "race_a")
    await chart("B5", ["SLICE_FILLED"],
                {"has_remaining": True, "under_max_slices": True,
                 "is_complete": False, "should_reprice": False}, "slice")
    await b225_handout()
    await b225_wait_true_handout()
    K.dump("v2_b2345.json")


asyncio.run(main())
