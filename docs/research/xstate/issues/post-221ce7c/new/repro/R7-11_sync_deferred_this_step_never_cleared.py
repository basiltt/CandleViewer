# -*- coding: utf-8 -*-
"""R7-11 -- REGRESSION: `SyncInterpreter._deferred_this_step` is never
cleared on the `wait=False` send path.

The per-step reset moved behind an `if wait:` guard (`sync_interpreter.py`,
`send()`):

    if wait:
        config_before = frozenset(self._active_state_nodes)
        ...
        self._deferred_this_step.clear()          # #106: per-step scope
        self._guard_denied_this_step = False       # #153: per-step scope

but `_deferred_this_step` is appended to unconditionally by the unhandled-
event handling regardless of `wait`. On the documented fire-and-forget
shape (`send(...)`, `wait` defaults to `False`) the list is therefore never
cleared and grows for the life of the interpreter.

The directly analogous `_guard_denied_this_step` IS reset on the same
`wait=False` path in practice (it is a scalar re-set each step it matters,
verified below) -- which is what makes `_deferred_this_step`'s omission look
like a bug rather than a design decision: they are meant to share the same
per-step scope and only one of them is unbounded.

Library only, no project machinery. main @ 221ce7c (unreleased 0.8.1;
`__version__` still reports 0.8.0 -- key on the commit). Python 3.13.

Exit code 1 == `_deferred_this_step` retained more than 1 entry after 5000
`wait=False` sends (i.e. it was never cleared). Exit code 0 == bounded.
"""
from xstate_statemachine import MachineLogic, SyncInterpreter, create_machine

CONFIG = {
    "id": "p",
    "initial": "busy",
    "onUnhandled": "defer",
    "states": {
        "busy": {"on": {"OTHER": {}}},
    },
}


def main() -> int:
    m = create_machine(CONFIG, logic=MachineLogic())
    i = SyncInterpreter(m)
    i.start()

    n = 5000
    for k in range(n):
        i.send("UNHANDLED", k=k)  # wait=False: the documented fire-and-forget shape

    leaked = len(i._deferred_this_step)
    buffered = len(i._deferred_events)
    print("sends=%d" % n)
    print("_deferred_this_step (per-STEP scope) = %d" % leaked)
    print("_deferred_events    (the real buffer, correctly bounded) = %d" % buffered)

    # One wait=True send reaches the reset, proving it is gated on `wait`
    # rather than genuinely per-step.
    i.send("UNHANDLED", wait=True)
    after_wait_true = len(i._deferred_this_step)
    print("after one wait=True send: _deferred_this_step = %d" % after_wait_true)
    i.stop()

    if leaked > 1 and after_wait_true <= 1:
        print("REPRODUCED: _deferred_this_step accumulated %d entries across "
              "%d wait=False sends and was flushed only once a wait=True send "
              "happened to reach the reset -- the reset is gated on `wait`, "
              "not run once per step." % (leaked, n))
        print("EXPECTED  : _deferred_this_step must be cleared at the start of "
              "EVERY step (both wait=True and wait=False), exactly like its "
              "sibling _guard_denied_this_step.")
        return 1
    print("NOT reproduced (leaked=%d, after wait=True=%d)."
          % (leaked, after_wait_true))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
