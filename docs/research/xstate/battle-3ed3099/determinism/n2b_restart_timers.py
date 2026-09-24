"""N2b -- #128 `restart_timers=True` repro, with a control.

CONTROL  : a FRESH interpreter on a SimulatedClock, driven into `armed`,
           then +200ms -> the `after: {50}` must fire.
SUBJECT  : the SAME machine restored from a snapshot taken in `armed` with
           `restart_timers=True`, then started, then +200ms.

`has_dormant_timers` is the library's own "is the parked work re-armed?"
signal. If it reports False (=re-armed) but the timer never fires, the signal
is lying and a restored replay silently stalls.

Run OUTSIDE an event loop: SimulatedClock.increment() does not fire timers
inside a running loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.clock import SimulatedClock  # noqa: E402

CFG = {
    "id": "tm",
    "initial": "idle",
    "context": {"late": 0},
    "states": {
        "idle": {"on": {"GO": "armed"}},
        "armed": {"after": {"50": {"target": "idle", "actions": ["late"]}}},
    },
}


def mk():
    def late(i, c, e, a):
        c["late"] += 1

    return create_machine(CFG, logic=MachineLogic(actions={"late": late}))


def leaves(i):
    return sorted(s.id for s in i._active_state_nodes if not s.states)


def sync_case():
    out = {}
    # --- CONTROL: fresh interpreter, never snapshotted
    c = SimulatedClock()
    i = SyncInterpreter(mk(), clock=c)
    i.start()
    i.send("GO")
    out["control_state_in_armed"] = leaves(i)
    out["control_has_dormant_timers"] = i.has_dormant_timers
    out["control_attached_settlers"] = len(c._settlers)
    c.increment(200)
    out["control_late"] = i.context["late"]
    out["control_state_after"] = leaves(i)
    snap = json.dumps(i.get_persisted_snapshot(), default=str)
    i.stop()

    # a snapshot taken WHILE armed (re-take: machine went back to idle above)
    c2 = SimulatedClock()
    j = SyncInterpreter(mk(), clock=c2)
    j.start()
    j.send("GO")
    armed_snap = json.dumps(j.get_persisted_snapshot(), default=str)
    j.stop()
    out["snapshot_state_ids"] = json.loads(armed_snap)["state_ids"]

    # --- SUBJECT: restore with restart_timers=True
    c3 = SimulatedClock()
    r = SyncInterpreter.from_snapshot(
        armed_snap, mk(), clock=c3, restart_timers=True
    )
    out["subject_dormant_before_start"] = r.has_dormant_timers
    r.start()
    out["subject_dormant_after_start"] = r.has_dormant_timers
    out["subject_attached_settlers"] = len(c3._settlers)
    out["subject_state_after_start"] = leaves(r)
    c3.increment(200)
    out["subject_late"] = r.context["late"]
    out["subject_state_after_200ms"] = leaves(r)
    # give the sync engine an explicit tick too, in case increment alone
    # is not the documented drive path
    if hasattr(r, "tick"):
        r.tick()
        out["subject_late_after_tick"] = r.context["late"]
        out["subject_state_after_tick"] = leaves(r)
    r.stop()
    out["VERDICT"] = (
        "OK"
        if out["subject_late"] >= 1
        else "TIMER-DID-NOT-FIRE despite has_dormant_timers=False"
    )
    return out


async def async_case():
    out = {}
    c = SimulatedClock()
    i = Interpreter(mk(), clock=c)
    await i.start()
    await i.send("GO")
    for _ in range(50):
        await asyncio.sleep(0)
    out["control_state_in_armed"] = leaves(i)
    out["control_attached_settlers"] = len(c._settlers)
    armed_snap = json.dumps(i.get_persisted_snapshot(), default=str)
    await c.increment(200)
    for _ in range(50):
        await asyncio.sleep(0)
    out["control_late"] = i.context["late"]
    out["control_state_after"] = leaves(i)
    await i.stop()

    c3 = SimulatedClock()
    r = Interpreter.from_snapshot(
        armed_snap, mk(), clock=c3, restart_timers=True
    )
    out["subject_dormant_before_start"] = r.has_dormant_timers
    await r.start()
    for _ in range(50):
        await asyncio.sleep(0)
    out["subject_dormant_after_start"] = r.has_dormant_timers
    out["subject_attached_settlers"] = len(c3._settlers)
    out["subject_state_after_start"] = leaves(r)
    await c3.increment(200)
    for _ in range(50):
        await asyncio.sleep(0)
    out["subject_late"] = r.context["late"]
    out["subject_state_after_200ms"] = leaves(r)
    await r.stop()
    out["VERDICT"] = (
        "OK"
        if out["subject_late"] >= 1
        else "TIMER-DID-NOT-FIRE despite has_dormant_timers=False"
    )
    return out


def main():
    res = {"sync": sync_case(), "async": asyncio.run(async_case())}
    for k, v in res.items():
        print(f"\n== {k.upper()} ==")
        for kk, vv in v.items():
            print(f"   {kk:34s}: {vv}")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "n2b_restart_timers.json"), "w") as f:
        json.dump(res, f, indent=2, default=str)
    print("\nwrote out/n2b_restart_timers.json")


if __name__ == "__main__":
    main()
