"""R5-13 repro: `SyncInterpreter.start()`'s restored branch returns before the
`SimulatedClock` settler is attached.

`sync_interpreter.py:268-283` handles the restart_services/restart_timers
resume path and `return self` at :283 -- before the
`if isinstance(self.clock, SimulatedClock): self.clock._attach(self.tick)` at
:307-308 that the normal start path runs. The re-armed `after` deadline is
registered on a clock that will never drive the interpreter:
`has_dormant_timers` reports False ("re-armed"), but `clock.increment()` past
the deadline does nothing. An explicit `tick()` recovers it, proving the
deadline exists and only the settler is missing. Control: a
constructor-injected clock fires on `increment()` alone.
Exits 1 while present, 0 once fixed. Stdlib + xstate_statemachine only.
"""

import json
import logging
import sys

from xstate_statemachine import MachineLogic, SyncInterpreter, create_machine
from xstate_statemachine.clock import SimulatedClock

CFG = {
    "id": "tm", "initial": "idle", "context": {"late": 0},
    "states": {
        "idle": {"on": {"GO": "armed"}},
        "armed": {"after": {"50": {"target": "idle", "actions": ["late"]}}},
    },
}


def mk():
    def late(i, c, e, a):
        c["late"] += 1

    return create_machine(CFG, logic=MachineLogic(actions={"late": late}))


def settlers(clock):
    return len(getattr(clock, "_settlers", []))


def main() -> int:
    # CONTROL: fresh interpreter, constructor-injected SimulatedClock
    c1 = SimulatedClock()
    ctrl = SyncInterpreter(mk(), clock=c1).start()
    ctrl.send("GO")
    ctrl_settlers = settlers(c1)
    c1.increment(200)
    ctrl_late = ctrl.context["late"]
    ctrl.stop()
    # snapshot taken while `armed`
    c2 = SimulatedClock()
    src = SyncInterpreter(mk(), clock=c2).start()
    src.send("GO")
    snap = json.dumps(src.get_persisted_snapshot(), default=str)
    src.stop()
    # SUBJECT: restore with restart_timers=True and a fresh SimulatedClock
    c3 = SimulatedClock()
    r = SyncInterpreter.from_snapshot(snap, mk(), clock=c3, restart_timers=True)
    r.start()
    subj_dormant = r.has_dormant_timers
    subj_settlers = settlers(c3)
    c3.increment(200)
    subj_late = r.context["late"]
    r.tick()  # the deadline IS there; only the settler is missing
    subj_late_after_tick = r.context["late"]
    r.stop()
    print("OBSERVED:")
    print("  CONTROL (ctor clock)  attached_settlers :", ctrl_settlers)
    print("  CONTROL               late after +200ms :", ctrl_late)
    print("  SUBJECT (restored)    has_dormant_timers:", subj_dormant)
    print("  SUBJECT               attached_settlers :", subj_settlers)
    print("  SUBJECT               late after +200ms :", subj_late)
    print("  SUBJECT               late after tick() :", subj_late_after_tick)
    print("EXPECTED:")
    print("  the restored interpreter attaches the settler exactly like the")
    print("  constructor path: attached_settlers=1 and late=1 after +200ms,")
    print("  with no explicit tick() required.")
    if subj_settlers == 0 and subj_late == 0 and ctrl_late >= 1:
        print("RESULT: FAIL - restored start() skipped clock._attach; "
              "has_dormant_timers=False is a false 're-armed' signal")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    sys.exit(main())
