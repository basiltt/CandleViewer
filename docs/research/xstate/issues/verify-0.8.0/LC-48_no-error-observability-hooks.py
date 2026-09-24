"""LC-48 verification on xstate-statemachine 0.8.0.

CHANGELOG: "Error-observability hooks on PluginBase (#33): on_transition_failed,
on_guard_error, on_unhandled_event, on_error, on_done. All implemented by
LoggingInspector." These are unconditional additive no-op hooks (no policy
flag) -- always fire on the applicable event; only one mode to test.

Beyond the original repro (which only checked the hooks are *declared*),
this verifies they actually *fire* with correct data and ordering per the
acceptance criteria:
  - on_unhandled_event fires exactly once for an unknown event type.
  - on_guard_error fires with the original exception AND on_guard_evaluated
    still reports result=False (behaviour unchanged).
  - on_transition_failed fires with the (action, exception) pairs BEFORE
    on_transition, for a transition whose action raised.
  - LoggingInspector implements all three new hooks (no AttributeError).

Exit 0 if all criteria hold, 1 otherwise.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from xstate_statemachine import Interpreter, LoggingInspector, MachineLogic, PluginBase, create_machine

logging.disable(logging.CRITICAL)

CFG = {
    "id": "order",
    "initial": "submitting",
    "context": {},
    "states": {
        "submitting": {
            "on": {
                "FILL": {"target": "filled", "actions": ["book"]},
                "CANCEL": {"target": "cancelled", "cond": "may_cancel"},
            }
        },
        "filled": {},
        "cancelled": {},
    },
}


def book(interpreter, context, event, action_def):
    raise RuntimeError("ledger write failed")


def may_cancel(context, event):
    raise RuntimeError("risk service unreachable")


class Recorder(PluginBase):
    def __init__(self) -> None:
        self.events: list = []

    def on_transition(self, interpreter, from_states, to_states, transition):
        self.events.append(("on_transition",))

    def on_transition_failed(self, interpreter, transition, failed_actions):
        self.events.append(("on_transition_failed", [(a.type, type(e).__name__) for a, e in failed_actions]))

    def on_guard_error(self, interpreter, guard_name, event, error):
        self.events.append(("on_guard_error", guard_name, type(error).__name__))

    def on_guard_evaluated(self, interpreter, guard_name, event, result):
        self.events.append(("on_guard_evaluated", guard_name, result))

    def on_unhandled_event(self, interpreter, event, active, disposition):
        self.events.append(("on_unhandled_event", event.type, disposition))


async def main() -> int:
    machine = create_machine(
        CFG, logic=MachineLogic(actions={"book": book}, guards={"may_cancel": may_cancel})
    )
    rec = Recorder()
    inspector = LoggingInspector()
    interp = Interpreter(machine).use(rec).use(inspector)
    await interp.start()
    await interp.send("TYPO_FILLED")
    await interp.send("CANCEL")
    await interp.send("FILL")
    await asyncio.sleep(0.05)
    await interp.stop()

    print("OBSERVED events:", rec.events)

    unhandled = [e for e in rec.events if e[0] == "on_unhandled_event" and e[1] == "TYPO_FILLED"]
    check_unhandled = unhandled == [("on_unhandled_event", "TYPO_FILLED", "ignored")]
    print(f"OBSERVED on_unhandled_event fires once for TYPO_FILLED: {check_unhandled}")

    guard_error = [e for e in rec.events if e[0] == "on_guard_error"]
    guard_eval = [e for e in rec.events if e[0] == "on_guard_evaluated"]
    check_guard = (
        guard_error == [("on_guard_error", "may_cancel", "RuntimeError")]
        and guard_eval == [("on_guard_evaluated", "may_cancel", False)]
    )
    print(f"OBSERVED on_guard_error fires + guard still False: {check_guard}")

    idx_failed = next((i for i, e in enumerate(rec.events) if e[0] == "on_transition_failed"), None)
    idx_transition = next((i for i, e in enumerate(rec.events) if e[0] == "on_transition"), None)
    check_failed = (
        idx_failed is not None
        and idx_transition is not None
        and idx_failed < idx_transition
        and rec.events[idx_failed][1] == [("book", "RuntimeError")]
    )
    print(f"OBSERVED on_transition_failed precedes on_transition with failed action info: {check_failed}")

    # LoggingInspector implements the new hooks without raising.
    check_inspector = all(
        callable(getattr(inspector, h, None))
        for h in ("on_transition_failed", "on_guard_error", "on_unhandled_event", "on_error", "on_done")
    )
    print(f"OBSERVED LoggingInspector implements new hooks: {check_inspector}")

    print(
        "EXPECTED all four checks True: unhandled event surfaced, guard error "
        "distinguishable, transition-failed ordering correct, inspector wired"
    )

    ok = check_unhandled and check_guard and check_failed and check_inspector
    print("RESULT:", "PASS (FIXED-DEFAULT)" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
