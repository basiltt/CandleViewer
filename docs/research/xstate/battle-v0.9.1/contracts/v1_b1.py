# -*- coding: utf-8 -*-
"""V1: B1 Order end-to-end on v0.9.0 -- happy path, rollback+onDone,
always->invoked-child, guard raise, defer/error, bounded RAISE inbox,
v3 snapshot/restore at every quiescence (chain_trips 0, plugins=).

#225 is honoured by the harness convention: an action that hands out a
receipt / spawns a worker is EXTERNAL traffic, so it uses
`asyncio.ensure_future(i.send(...))` and never awaits in-step.

STANDALONE: stdlib + xstate_statemachine only, neutral cwd.
"""
from __future__ import annotations
import asyncio, json, os, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cv9 as K  # noqa: E402
os.chdir("<home>")

GOOD = {"passes_all_gates": True, "is_terminal_ack": True,
        "is_fill": True, "is_fully_filled": True,
        "needs_protection": False, "is_duplicate_exec": False,
        "should_reconcile": False}


async def happy():
    c = K.cfg("B1")
    st = K.Stub(c, guard_vals=GOOD)
    r = await K.drive(c, st, ["VALIDATE", "SUBMIT"])
    K.rec("V1.B1.happy_advances", r["states"] != ["order.lifecycle.draft"],
          "states=%s status=%s" % (r["states"], r["status"]))
    K.rec("V1.B1.happy_snapshot_ok", r["snapshot_ok"], "; ".join(r["notes"])[:400])
    K.rec("V1.B1.happy_chain_trips_zero", r["chain_trips"] == 0,
          "chain_trips=%r lce=%s" % (r["chain_trips"], r["last_chain_error"]))
    K.rec("V1.B1.happy_no_action_errors", not r["action_errors"],
          "%r" % (r["action_errors"][:4],))
    K.rec("V1.B1.happy_no_stranded", not r["stranded"], "%r" % (r["stranded"][:4],))
    return r


async def reject_path():
    """The unguarded second arm must land in `rejected`, not stall."""
    c = K.cfg("B1")
    st = K.Stub(c, guard_vals={"passes_all_gates": False})
    r = await K.drive(c, st, ["VALIDATE"])
    K.rec("V1.B1.reject_arm_lands",
          any("rejected" in s for s in r["states"]),
          "states=%s actions=%s" % (r["states"], r["actions"][-4:]))
    K.rec("V1.B1.reject_snapshot_ok", r["snapshot_ok"], "; ".join(r["notes"])[:300])


async def guard_raise():
    """A raising guard must be observable (on_guard_error / last_error) and
    must NOT take the machine down."""
    c = K.cfg("B1")
    st = K.Stub(c, guard_vals=GOOD, guard_raise={"passes_all_gates"})
    r = await K.drive(c, st, ["VALIDATE"], snapshots=False)
    K.rec("V1.B1.guard_raise_observed",
          bool(r["guard_errors"]) or r["error"] is not None,
          "guard_errors=%r error=%r states=%s"
          % (r["guard_errors"][:2], r["error"], r["states"]))
    K.rec("V1.B1.guard_raise_not_fatal", r["status"] in ("running", "done"),
          "status=%r states=%s" % (r["status"], r["states"]))


async def action_raise():
    """A raising action must reach on_action_error and not strand the run."""
    c = K.cfg("B1")
    st = K.Stub(c, guard_vals=GOOD, raising={"stamp_validated"})
    r = await K.drive(c, st, ["VALIDATE"], snapshots=False)
    K.rec("V1.B1.action_raise_observed",
          bool(r["action_errors"]) or r["error"] is not None,
          "action_errors=%r error=%r" % (r["action_errors"][:2], r["error"]))
    K.rec("V1.B1.action_raise_chain_clean", r["chain_trips"] == 0,
          "chain_trips=%r" % (r["chain_trips"],))


async def unknown_event_strict():
    """strict=True: an undeclared event type is refused, reported, and the
    machine stays up."""
    c = K.cfg("B1")
    st = K.Stub(c, guard_vals=GOOD)
    m, i, p = await K.new_async(c, st)
    r = await K.send(i, "NOT_A_REAL_EVENT")
    await K.quiesce(i, 2)
    K.rec("V1.B1.strict_refuses_unknown",
          (not r["ok"]) or bool(p.invalid) or bool(p.dropped)
          or bool(p.unhandled),
          "send=%r invalid=%r dropped=%r unhandled=%r"
          % (r.get("exc"), p.invalid[:2], p.dropped[:2], p.unhandled[:2]))
    K.rec("V1.B1.strict_survives_unknown", i.status == "running",
          "status=%r states=%s" % (i.status, K.ids(i)))
    await i.stop()


async def sync_parity():
    c = K.cfg("B1")
    a = await K.drive(c, K.Stub(c, guard_vals=GOOD), ["VALIDATE"],
                      snapshots=False)
    s = K.drive_sync(c, K.Stub(c, guard_vals=GOOD, sync=True), ["VALIDATE"])
    K.rec("V1.B1.sync_parity_states", a["states"] == s["states"],
          "async=%s sync=%s" % (a["states"], s["states"]))
    K.rec("V1.B1.sync_parity_chain_trips",
          a["chain_trips"] == s["chain_trips"] == 0,
          "async=%r sync=%r" % (a["chain_trips"], s["chain_trips"]))


async def main():
    await happy()
    await reject_path()
    await guard_raise()
    await action_raise()
    await unknown_event_strict()
    await sync_parity()
    K.dump("v1_b1.json")


asyncio.run(main())
