# -*- coding: utf-8 -*-
"""C4 -- the NON-quiescent snapshot, and what CV-C20 must gate on.

(1) snapshot while an invoke is in flight (B6 `submitting_slice`): allowed
    or refused? what does it restore as?
(2) snapshot while events are HELD under `onUnhandled: "defer"`: does the
    deferral buffer round-trip?
(3) snapshot inside a `send(wait=True)` that is mid-macrostep -- the #102
    window -- driven from an action hook.
"""
from __future__ import annotations

import asyncio
import json

import cvlib
from cvlib import Rig
from xstate_statemachine import Interpreter
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.exceptions import SnapshotMidStepError


async def c1_invoke_in_flight():
    cfg = cvlib.load("B6")
    rig = Rig(service_mode={"submit_child": "gate"})
    _m, interp, plug, clock = cvlib.new_interp(cfg, rig)
    await interp.start()
    await interp.send("SLICE_DUE")
    await asyncio.sleep(cvlib.SETTLE * 2)
    row = {
        "case": "snapshot with invoke in flight",
        "states": sorted(interp.current_state_ids),
        "queue_depth": interp.queue_depth,
        "deferred_count": interp.deferred_count,
        "pending_invocations": [p.src for p in interp.pending_invocations()],
    }
    try:
        blob = interp.get_snapshot()
        row["snapshot"] = "OK"
    except SnapshotMidStepError as exc:
        row["snapshot"] = "SnapshotMidStepError"
        blob = None
    rig.gate("submit_child").set()
    interp._plugins = []
    await interp.stop()
    if blob:
        rig2 = Rig()
        m2 = cvlib.build(cfg, rig2)
        i2 = Interpreter.from_snapshot(
            blob, m2, restart_services=False, clock=SimulatedClock()
        )
        p2 = cvlib.TraceP()
        i2.use(p2)
        await i2.start()
        await asyncio.sleep(cvlib.SETTLE * 4)
        row["restored_states"] = sorted(i2.current_state_ids)
        row["restored_status"] = i2.status
        row["restored_pending"] = [p.src for p in i2.pending_invocations()]
        # is it inert? poke it with an event the state does not handle
        r = await i2.send("USER_CANCEL", wait=True)
        await asyncio.sleep(cvlib.SETTLE * 3)
        row["after_cancel"] = sorted(i2.current_state_ids)
        row["cancel_receipt"] = {
            "changed": r.changed, "deferred": r.deferred,
            "error": repr(r.error),
        }
        row["STRANDED_no_restart_services"] = (
            row["after_cancel"] == ["twap.submitting_slice"]
        )
        await i2.stop()

        # now the restart_services=True variant
        rig3 = Rig()
        m3 = cvlib.build(cfg, rig3)
        i3 = Interpreter.from_snapshot(
            blob, m3, restart_services=True, clock=SimulatedClock()
        )
        await i3.start()
        await asyncio.sleep(cvlib.SETTLE * 4)
        row["restart_services_True_states"] = sorted(i3.current_state_ids)
        row["restart_services_True_calls"] = list(rig3.calls)
        await i3.stop()
    return row


async def c2_deferred_roundtrip():
    cfg = cvlib.load("B10")
    rig = Rig(guard_values={"delivery_attempts_left": False},
              service_mode={"dispatch_to_channels": "fail"})
    _m, interp, plug, clock = cvlib.new_interp(cfg, rig)
    await interp.start()
    await interp.send("CONDITION_MET")
    await asyncio.sleep(cvlib.SETTLE * 4)
    await interp.send("RESOLVE")  # no edge in delivery_failed -> HELD
    await asyncio.sleep(cvlib.SETTLE * 2)
    row = {
        "case": "snapshot with a HELD (deferred) event",
        "states": sorted(interp.current_state_ids),
        "deferred_count_before": interp.deferred_count,
        "queue_depth": interp.queue_depth,
    }
    try:
        blob = interp.get_snapshot()
        row["snapshot"] = "OK"
    except Exception as exc:  # noqa: BLE001
        row["snapshot"] = type(exc).__name__
        blob = None
    interp._plugins = []
    await interp.stop()
    if blob:
        rig2 = Rig()
        m2 = cvlib.build(cfg, rig2)
        i2 = Interpreter.from_snapshot(blob, m2, clock=SimulatedClock())
        p2 = cvlib.TraceP()
        i2.use(p2)
        await i2.start()
        await asyncio.sleep(cvlib.SETTLE * 2)
        row["deferred_count_after_restore"] = i2.deferred_count
        await i2.send("ACK")
        await asyncio.sleep(cvlib.SETTLE * 4)
        row["after_ack"] = sorted(i2.current_state_ids)
        row["HELD_EVENT_SURVIVED"] = row["after_ack"] == ["alert.resolved"]
        await i2.stop()
    return row


async def c3_midstep_window():
    """#102: snapshot taken from inside an action, mid-macrostep."""
    cfg = cvlib.load("B9")
    seen = {}

    def hook(interp, ctx, event):
        try:
            interp.get_snapshot()
            seen["result"] = "ALLOWED (mid-macrostep snapshot succeeded)"
        except SnapshotMidStepError:
            seen["result"] = "SnapshotMidStepError (refused -- #102 holds)"
        except Exception as exc:  # noqa: BLE001
            seen["result"] = type(exc).__name__ + ": " + str(exc)[:120]

    rig = Rig(
        guard_values={"promotion_gate_satisfied_and_permitted": True,
                      "condition_true": True},
        action_hooks={"assert_safety_limits": hook},
    )
    _m, interp, plug, clock = cvlib.new_interp(cfg, rig)
    await interp.start()
    for ev in ("SAVE", "ARM_REQUESTED", "TRIGGER"):
        await interp.send(ev)
        await asyncio.sleep(cvlib.SETTLE * 2)
    await asyncio.sleep(cvlib.SETTLE * 3)
    await interp.stop()
    return {
        "case": "#102 mid-macrostep snapshot from inside an entry action",
        "result": seen.get("result", "<hook never ran>"),
    }


async def main():
    rows = [
        await c1_invoke_in_flight(),
        await c2_deferred_roundtrip(),
        await c3_midstep_window(),
    ]
    print(json.dumps(rows, indent=2, default=str))


asyncio.run(main())
