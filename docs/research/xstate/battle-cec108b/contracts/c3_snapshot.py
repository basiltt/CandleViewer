# -*- coding: utf-8 -*-
"""C3 -- snapshot / restore at quiescence between EVERY macrostep.

For each machine and each representative script:
  * run uninterrupted -> reference trace;
  * for every k in 0..len(script): drive k events, quiesce, snapshot
    (must NEVER raise SnapshotMidStepError at a quiescent point), restore
    into a fresh interpreter, resume with the remainder, compare.

Quiescence gate per CV-C20: queue_depth == 0 and deferred_count == 0.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List

import cvlib
from cvlib import Rig
from xstate_statemachine import Interpreter
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.exceptions import SnapshotMidStepError

RESULTS: List[Dict[str, Any]] = []


def mkrig(spec):
    return Rig(
        guard_values=dict(spec.get("guards") or {}),
        service_mode=dict(spec.get("services") or {}),
    )


async def run_plain(cfg, spec, script):
    rig = mkrig(spec)
    _m, interp, plug, clock = cvlib.new_interp(cfg, rig)
    await interp.start()
    await asyncio.sleep(cvlib.SETTLE)
    for ev in script:
        if interp.status != "running":
            break
        await cvlib.apply(interp, clock, ev)
    await asyncio.sleep(cvlib.SETTLE)
    out = cvlib.snap(interp, plug)
    await interp.stop()
    return out


async def run_interrupted(cfg, spec, script, k):
    rig = mkrig(spec)
    m = cvlib.build(cfg, rig)
    clock = SimulatedClock()
    interp = Interpreter(m, clock=clock)
    plug = cvlib.TraceP()
    interp.use(plug)
    await interp.start()
    await asyncio.sleep(cvlib.SETTLE)
    for ev in script[:k]:
        if interp.status != "running":
            break
        await cvlib.apply(interp, clock, ev)
    await asyncio.sleep(cvlib.SETTLE)

    note = {"k": k, "quiescent": None, "snapshot": None}
    note["quiescent"] = {
        "queue_depth": interp.queue_depth,
        "deferred_count": interp.deferred_count,
    }
    try:
        blob = interp.get_snapshot()
        note["snapshot"] = "OK"
    except SnapshotMidStepError as exc:
        note["snapshot"] = "SnapshotMidStepError: " + str(exc)[:160]
        await interp.stop()
        return None, note
    except Exception as exc:  # noqa: BLE001
        note["snapshot"] = type(exc).__name__ + ": " + str(exc)[:160]
        await interp.stop()
        return None, note

    now = clock.now()
    pre_actions = list(plug.actions)
    interp._plugins = []
    await interp.stop()

    # --- restore into a FRESH interpreter (process-death semantics)
    rig2 = mkrig(spec)
    m2 = cvlib.build(cfg, rig2)
    clock2 = SimulatedClock()
    clock2._now = now
    i2 = Interpreter.from_snapshot(
        blob, m2, restart_services=True, restart_timers=True, clock=clock2
    )
    note["has_dormant_timers"] = i2.has_dormant_timers
    note["pending_invocations"] = [
        p.src for p in i2.pending_invocations()
    ]
    plug2 = cvlib.TraceP()
    plug2.actions = pre_actions
    i2.use(plug2)
    await i2.start()
    await asyncio.sleep(cvlib.SETTLE * 2)
    for ev in script[k:]:
        if i2.status != "running":
            break
        await cvlib.apply(i2, clock2, ev)
    await asyncio.sleep(cvlib.SETTLE)
    out = cvlib.snap(i2, plug2)
    await i2.stop()
    return out, note


SCRIPTS = {
    "B6": (
        {"guards": {}},
        ["SLICE_DUE", "SLICE_DUE", "USER_PAUSE", "RESUME", "DURATION_END",
         "CHILDREN_TERMINAL"],
    ),
    "B7": (
        {"guards": {
            "drift_over_threshold_and_interval_elapsed_and_budget_ok": True}},
        ["BOOK_TARGET_MOVED", "CHILD_PARTIAL", "USER_PAUSE", "RESUME",
         "CHILD_FILLED", "CHILDREN_TERMINAL"],
    ),
    "B8": (
        {"guards": {"exchange_reports_sl": True, "tightens_only": True,
                    "sl_observed": True}},
        ["POSITION_OPENED", "SCAN_DUE", "TIGHTEN_SL", "SCAN_DUE",
         "POSITION_FLAT"],
    ),
    "B9": (
        {"guards": {"promotion_gate_satisfied_and_permitted": True,
                    "condition_true": True}},
        ["SAVE", "ARM_REQUESTED", "TRIGGER", "COOLDOWN_DUE", "TRIGGER",
         "COOLDOWN_DUE"],
    ),
    "B10": (
        {"guards": {"all_channels_ok": True}},
        ["CONDITION_MET", "ACK", "RESOLVE"],
    ),
}


async def main():
    for bid, (spec, script) in SCRIPTS.items():
        cfg = cvlib.load(bid)
        ref = await run_plain(cfg, spec, script)
        row = {
            "machine": bid,
            "script": script,
            "reference": {"states": ref.states, "status": ref.status,
                          "actions": ref.actions},
            "crashpoints": [],
        }
        for k in range(len(script) + 1):
            out, note = await run_interrupted(cfg, spec, script, k)
            entry = dict(note)
            if out is None:
                entry["verdict"] = "SNAPSHOT-REFUSED"
            else:
                same_states = out.states == ref.states
                same_actions = out.actions == ref.actions
                entry["verdict"] = (
                    "MATCH" if (same_states and same_actions)
                    else ("STATES-MATCH/TRACE-DIFF" if same_states
                          else "DIVERGED")
                )
                entry["resumed_states"] = out.states
                entry["resumed_status"] = out.status
                if not same_actions:
                    entry["ref_actions"] = ref.actions
                    entry["got_actions"] = out.actions
            row["crashpoints"].append(entry)
        RESULTS.append(row)

    print(json.dumps(RESULTS, indent=2, default=str))
    print("\n=== SUMMARY ===")
    for r in RESULTS:
        vs = [c["verdict"] for c in r["crashpoints"]]
        print(r["machine"], dict((v, vs.count(v)) for v in sorted(set(vs))))
    midstep = [
        (r["machine"], c["k"], c["snapshot"])
        for r in RESULTS for c in r["crashpoints"]
        if str(c.get("snapshot", "")).startswith("SnapshotMidStep")
    ]
    print("SnapshotMidStepError at a quiescent point:", midstep or "NONE")


asyncio.run(main())
