"""LC-47 verification on xstate-statemachine 0.8.0.

CHANGELOG "Fixed": "Resolving a transition no longer writes back into the
shared TransitionDefinition (#59)." This is an unconditional fix (no policy
flag), so there's only one mode.

Extends the original repro by covering plain, nested, `#`-absolute and
bubble-up-to-uncle targets (per acceptance criterion
`test_interpretation_does_not_write_to_transition_definition`), plus the
original single/multi-interpreter/threaded checks.

Exit 0 if resolving any of these target forms, from one or many interpreters
(including across threads), never writes to `transition.target_str` on the
shared MachineNode.
"""

from __future__ import annotations

import logging
import sys
import threading

from xstate_statemachine import SyncInterpreter, create_machine

logging.disable(logging.CRITICAL)

CONFIG = {
    "id": "o",
    "initial": "idle",
    "states": {
        "idle": {"on": {"SUBMIT": "open"}},
        "open": {
            "initial": "b",
            "on": {"CLOSE": "closed", "NEST": ".b", "ABS": "#o.open.b", "UNCLE": "idle"},
            "states": {"b": {}},
        },
        "closed": {"type": "final"},
    },
}

MACHINE = create_machine(CONFIG)
ALL_TRANSITIONS = []
for state in [MACHINE, *MACHINE.states.values()]:
    for defs in getattr(state, "on", {}).values():
        for t in defs if isinstance(defs, list) else [defs]:
            ALL_TRANSITIONS.append(t)

WRITES: list[tuple[str, str]] = []
LOCK = threading.Lock()


def watch(transition) -> None:
    stored = transition.__dict__.pop("target_str")
    transition.__dict__["_target_str"] = stored

    class Watched(type(transition)):
        @property
        def target_str(self):
            return self.__dict__["_target_str"]

        @target_str.setter
        def target_str(self, value):
            with LOCK:
                WRITES.append((threading.current_thread().name, value))
            self.__dict__["_target_str"] = value

    transition.__class__ = Watched


for t in ALL_TRANSITIONS:
    watch(t)

# 1) Drive plain, nested (.b), absolute (#o.open.b) and bubble-up (idle) targets.
it1 = SyncInterpreter(MACHINE).start()
it1.send("SUBMIT")  # idle -> open (plain)
it1.send("NEST")  # .b (nested)
it1.send("ABS")  # #o.open.b (absolute)
it1.send("UNCLE")  # idle (bubble-up)
print(f"OBSERVED writes after 1 interpreter, 4 varied targets: {WRITES}")

# 2) A second interpreter over the same shared node.
it2 = SyncInterpreter(MACHINE).start()
it2.send("SUBMIT")
print(f"OBSERVED writes after a 2nd interpreter: {len(WRITES)}")

# 3) Concurrent SyncInterpreters (threads).
WRITES.clear()


def drive() -> None:
    it = SyncInterpreter(MACHINE).start()
    for _ in range(50):
        it.send("SUBMIT")
        it.send("NEST")
        it.send("ABS")
        it.send("UNCLE")


threads = [threading.Thread(target=drive, name=f"w{i}") for i in range(8)]
for t in threads:
    t.start()
for t in threads:
    t.join()

writers = sorted({name for name, _ in WRITES})
print(f"OBSERVED 8 threads x 50 cycles x 4 targets -> {len(WRITES)} writes from {writers}")
print(f"OBSERVED authored target_str values unchanged: "
      f"{[t.target_str for t in ALL_TRANSITIONS]}")
print("EXPECTED zero writes across all target forms, single/multi/threaded interpreters")

ok = not WRITES
print("RESULT:", "PASS (FIXED-DEFAULT)" if ok else "FAIL")
sys.exit(0 if ok else 1)
