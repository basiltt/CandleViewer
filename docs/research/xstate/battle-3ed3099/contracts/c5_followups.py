# -*- coding: utf-8 -*-
"""C5 -- two narrow follow-ups from C4.

(1) `pending_invocations()` read **0** on a LIVE interpreter parked in
    `submitting_slice` with `submit_child` genuinely in flight, but **1**
    on the interpreter restored from that same snapshot. CV-C20 tells
    `cv.statechart.persistence` to reconcile every `pending_invocations()`
    entry -- so which side is authoritative?

(2) C4 case 3 took a snapshot from inside an ENTRY action and it was
    ALLOWED. Entry actions may run after the configuration has settled, so
    that is not necessarily the #102 window. Re-probe from a TRANSITION
    action and an EXIT action, which sit between the exit set and the entry
    set.
"""
from __future__ import annotations

import asyncio
import json

import cvlib
from cvlib import Rig
from xstate_statemachine.exceptions import SnapshotMidStepError


async def p1_pending_invocations():
    cfg = cvlib.load("B6")
    rig = Rig(service_mode={"submit_child": "gate"})
    _m, interp, plug, clock = cvlib.new_interp(cfg, rig)
    await interp.start()
    rows = []
    await interp.send("SLICE_DUE")
    for i in range(4):
        await asyncio.sleep(cvlib.SETTLE)
        rows.append({
            "t": i,
            "states": sorted(interp.current_state_ids),
            "pending_invocations": [p.src for p in interp.pending_invocations()],
            "service_started": rig.calls.count("S:submit_child"),
        })
    blob = interp.get_snapshot()
    import json as _j
    snap = _j.loads(blob)
    rig.gate("submit_child").set()
    interp._plugins = []
    await interp.stop()
    return {
        "case": "(1) pending_invocations: live vs snapshot",
        "live_readings": rows,
        "snapshot_records_invocations": bool(
            _j.dumps(snap).count("submit_child")
        ),
        "snapshot_keys": sorted(snap.keys()),
        "LIVE_READS_ZERO_WHILE_SERVICE_RUNNING": (
            rows[-1]["pending_invocations"] == []
            and rows[-1]["service_started"] == 1
        ),
    }


async def p2_true_midstep():
    """Snapshot from a transition action and from an exit action."""
    cfg = cvlib.load("B9")
    results = {}

    def mk(where):
        def hook(interp, ctx, event):
            try:
                interp.get_snapshot()
                results[where] = "ALLOWED"
            except SnapshotMidStepError:
                results[where] = "SnapshotMidStepError"
            except Exception as exc:  # noqa: BLE001
                results[where] = type(exc).__name__
        return hook

    # `unsubscribe_triggers` is an EXIT action of `armed`;
    # `record_skip_debounced` is a pure TRANSITION action (internal edge).
    rig = Rig(
        guard_values={"promotion_gate_satisfied_and_permitted": True,
                      "condition_true": True},
        action_hooks={
            "unsubscribe_triggers": mk("exit-action(armed)"),
            "record_skip_debounced": mk("transition-action(internal)"),
            "subscribe_triggers": mk("entry-action(armed)"),
        },
    )
    _m, interp, plug, clock = cvlib.new_interp(cfg, rig)
    await interp.start()
    for ev in ("SAVE", "ARM_REQUESTED"):
        await interp.send(ev)
        await asyncio.sleep(cvlib.SETTLE * 2)
    rig.guard_values["debounce_blocked"] = True
    await interp.send("TRIGGER")   # internal edge -> transition action
    await asyncio.sleep(cvlib.SETTLE * 2)
    rig.guard_values["debounce_blocked"] = False
    await interp.send("TRIGGER")   # leaves armed -> exit action
    await asyncio.sleep(cvlib.SETTLE * 3)
    await interp.stop()
    return {
        "case": "(2) where is the #102 window actually enforced?",
        "results": results,
    }


async def main():
    rows = [await p1_pending_invocations(), await p2_true_midstep()]
    print(json.dumps(rows, indent=2, default=str))


asyncio.run(main())
