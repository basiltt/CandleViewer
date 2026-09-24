# -*- coding: utf-8 -*-
"""C7 -- cross-machine listed scenarios that land inside B6..B10, plus
sync-engine parity (informational).

(a) B13-analogue -- reconnect / resync: WS_DISCONNECT freezes the algo,
    RESUME goes through `reconciling` (re-arming deadlines) and NOT
    straight back to `armed`. Also the `on_disconnect_is_freeze=False`
    branch.
(b) B19-analogue -- reconciliation divergence: `reconcile_children` fails
    -> `failed`; and the INV-B6-b claim that `rearm_deadlines_from_context`
    is the ONLY way deadlines return after a restore.
(c) sync-engine parity on the same scripts (parity info only; async is
    primary).
"""
from __future__ import annotations

import asyncio
import json

import cvlib
from cvlib import Rig
from xstate_statemachine import SyncInterpreter
from xstate_statemachine.clock import SimulatedClock


async def a_reconnect():
    cfg = cvlib.load("B6")
    rows = []
    # freeze policy ON
    rig = Rig(guard_values={"on_disconnect_is_freeze": True})
    _m, interp, plug, clock = cvlib.new_interp(cfg, rig)
    await interp.start()
    await cvlib.apply(interp, clock, "WS_DISCONNECT")
    frozen = sorted(interp.current_state_ids)
    await cvlib.apply(interp, clock, "RESUME")
    await asyncio.sleep(cvlib.SETTLE * 3)
    rows.append({
        "case": "(a1) WS_DISCONNECT freeze -> RESUME via reconciling",
        "frozen": frozen,
        "after_resume": sorted(interp.current_state_ids),
        "went_through_reconciling":
            "S:reconcile_children" in rig.calls,
        "rearmed_deadlines":
            "A:rearm_deadlines_from_context" in rig.calls,
        "calls": rig.calls,
    })
    await interp.stop()

    # freeze policy OFF -> WS_DISCONNECT must NOT pause (guard denies)
    rig = Rig(guard_values={"on_disconnect_is_freeze": False})
    _m, interp, plug, clock = cvlib.new_interp(cfg, rig)
    await interp.start()
    await cvlib.apply(interp, clock, "WS_DISCONNECT")
    rows.append({
        "case": "(a2) freeze policy OFF: WS_DISCONNECT is held, not applied",
        "states": sorted(interp.current_state_ids),
        "deferred": interp.deferred_count,
        "unhandled": list(plug.unhandled),
    })
    await interp.stop()
    return rows


async def b_divergence():
    cfg = cvlib.load("B6")
    rows = []
    rig = Rig(guard_values={"on_disconnect_is_freeze": True},
              service_mode={"reconcile_children": "fail"})
    _m, interp, plug, clock = cvlib.new_interp(cfg, rig)
    await interp.start()
    await cvlib.apply(interp, clock, "USER_PAUSE")
    await cvlib.apply(interp, clock, "RESUME")
    await asyncio.sleep(cvlib.SETTLE * 3)
    rows.append({
        "case": "(b1) reconciliation divergence -> terminal failed",
        "states": sorted(interp.current_state_ids),
        "is_terminal_failure": sorted(interp.current_state_ids) == ["twap.failed"],
    })
    await interp.stop()

    # (b2) INV-B6-b: after a restore, are deadlines back without reconciling?
    rig = Rig()
    _m, interp, plug, clock = cvlib.new_interp(cfg, rig)
    await interp.start()
    await asyncio.sleep(cvlib.SETTLE)
    blob = interp.get_snapshot()
    interp._plugins = []
    await interp.stop()
    rig2 = Rig()
    m2 = cvlib.build(cfg, rig2)
    from xstate_statemachine import Interpreter

    i2 = Interpreter.from_snapshot(blob, m2, clock=SimulatedClock(),
                                   restart_timers=True)
    await i2.start()
    await asyncio.sleep(cvlib.SETTLE * 2)
    rows.append({
        "case": "(b2) INV-B6-b: restore does not silently re-register "
                "deadlines",
        "restored_states": sorted(i2.current_state_ids),
        "register_ran_on_restore":
            "A:register_deadlines_with_scheduler" in rig2.calls,
        "rearm_ran_on_restore":
            "A:rearm_deadlines_from_context" in rig2.calls,
        "has_dormant_timers": i2.has_dormant_timers,
        "calls": rig2.calls,
    })
    await i2.stop()
    return rows


def c_sync_parity():
    """Same scripts on SyncInterpreter. Parity information only."""
    out = []
    specs = [
        ("B6", {"guards": {}},
         ["SLICE_DUE", "SLICE_DUE", "DURATION_END", "CHILDREN_TERMINAL"]),
        ("B10", {"guards": {"all_channels_ok": True}},
         ["CONDITION_MET", "ACK", "RESOLVE"]),
        ("B9", {"guards": {"promotion_gate_satisfied_and_permitted": True,
                           "condition_true": True}},
         ["SAVE", "ARM_REQUESTED", "TRIGGER", "COOLDOWN_DUE"]),
    ]
    for bid, spec, script in specs:
        cfg = cvlib.load(bid)
        rig = Rig(guard_values=dict(spec["guards"]))
        # sync engine needs plain-def services
        logic = cvlib.make_logic(cfg, rig)
        for k in list(logic.services):
            def mk(n):
                def fn(interp, ctx, event):  # noqa: ANN001
                    rig.calls.append("S:" + n)
                    return {"svc": n}
                fn.__name__ = n
                return fn
            logic.services[k] = mk(k)
        from xstate_statemachine import create_machine

        m = create_machine(cfg, logic=logic)
        si = SyncInterpreter(m)
        plug = cvlib.TraceP()
        si.use(plug)
        row = {"machine": bid, "script": script}
        try:
            si.start()
            for ev in script:
                if si.status != "running":
                    break
                si.send(ev)
            row["sync_states"] = sorted(si.current_state_ids)
            row["sync_status"] = si.status
            row["sync_actions"] = list(plug.actions)
            si.stop()
        except Exception as exc:  # noqa: BLE001
            row["sync_error"] = type(exc).__name__ + ": " + str(exc)[:200]
        out.append(row)
    return out


async def main():
    rows = {"a_reconnect": await a_reconnect(),
            "b_divergence": await b_divergence()}
    rows["c_sync_parity"] = c_sync_parity()
    print(json.dumps(rows, indent=2, default=str))


asyncio.run(main())
