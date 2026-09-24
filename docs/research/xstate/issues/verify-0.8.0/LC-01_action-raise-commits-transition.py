"""LC-01 verification on xstate-statemachine 0.8.0.

Issue: an action that raises still committed the transition, with no
programmatic error channel (0.7.0). The 0.8.0 fix is the per-machine policy
``actionErrorPolicy: "continue" | "rollback" | "fail"``. Default is
"continue" (0.7.x-identical committed transition, but now OBSERVABLE via
``on_transition_failed`` / ``interpreter.last_transition_ok``).

This script checks:
  1. DEFAULT ("continue" - not set): transition still commits (0.7.x
     semantics preserved), but interpreter.last_transition_ok is False and
     the failure is observable.
  2. OPT-IN "rollback": transition is NOT committed, state stays at 'oms.a',
     entry_b did not run, context restored.
  3. OPT-IN "fail": interpreter reaches status == "error" with the original
     RuntimeError retrievable via interpreter.error.__cause__.

Exit 0 if all three behave per the issue's acceptance criteria (defaults
preserved AND opt-in escape hatches work), 1 otherwise.
"""

from __future__ import annotations

import logging
import sys
from typing import Any, Dict, List

from xstate_statemachine import MachineLogic, SyncInterpreter, create_machine
from xstate_statemachine.plugins import PluginBase

logging.disable(logging.CRITICAL)


def _config(policy: str = None) -> Dict[str, Any]:
    cfg: Dict[str, Any] = {
        "id": "oms",
        "initial": "a",
        "context": {"trace": []},
        "states": {
            "a": {
                "on": {
                    "GO": {"target": "b", "actions": ["first", "explode", "third"]}
                }
            },
            "b": {"entry": ["entry_b"]},
        },
    }
    if policy is not None:
        cfg["actionErrorPolicy"] = policy
    return cfg


def _logic() -> MachineLogic:
    def first(i, c, e, a):
        c["trace"].append("first")

    def explode(i, c, e, a):
        c["trace"].append("explode")
        raise RuntimeError("exchange rejected the order")

    def third(i, c, e, a):
        c["trace"].append("third")

    def entry_b(i, c, e, a):
        c["trace"].append("entry_b")

    return MachineLogic(
        actions={
            "first": first,
            "explode": explode,
            "third": third,
            "entry_b": entry_b,
        }
    )


class Spy(PluginBase):
    def __init__(self) -> None:
        self.failed: List[List[str]] = []

    def on_transition_failed(self, interp, transition, failed_actions):
        self.failed.append([a.type for a, _ in failed_actions])


def check_default() -> bool:
    spy = Spy()
    interp = SyncInterpreter(create_machine(_config(), logic=_logic()))
    interp.use(spy)
    interp.start()
    interp.send("GO")

    state = sorted(interp.current_state_ids)
    trace = list(interp.context["trace"])
    ok = interp.last_transition_ok

    print("DEFAULT  OBSERVED state:", state, "trace:", trace, "last_transition_ok:", ok, "failed:", spy.failed)
    expected_state = ["oms.b"]
    expected_trace = ["first", "explode", "entry_b"]
    passed = (
        state == expected_state
        and trace == expected_trace
        and ok is False
        and spy.failed == [["explode"]]
    )
    print("DEFAULT  EXPECTED state:", expected_state, "trace:", expected_trace, "last_transition_ok: False, failed: [['explode']]")
    return passed


def check_rollback() -> bool:
    spy = Spy()
    interp = SyncInterpreter(create_machine(_config("rollback"), logic=_logic()))
    interp.use(spy)
    interp.start()
    interp.send("GO")

    state = sorted(interp.current_state_ids)
    trace = list(interp.context["trace"])
    ok = interp.last_transition_ok

    print("ROLLBACK OBSERVED state:", state, "trace:", trace, "last_transition_ok:", ok)
    passed = state == ["oms.a"] and "entry_b" not in trace and ok is False
    print("ROLLBACK EXPECTED state: ['oms.a'], entry_b absent, last_transition_ok: False")
    return passed


def check_fail() -> bool:
    interp = SyncInterpreter(create_machine(_config("fail"), logic=_logic()))
    interp.start()
    interp.send("GO")

    status = interp.status
    err = interp.error
    cause_ok = isinstance(getattr(err, "__cause__", None), RuntimeError)

    print("FAIL     OBSERVED status:", status, "error:", type(err).__name__, "cause is RuntimeError:", cause_ok)
    passed = status == "error" and cause_ok
    print("FAIL     EXPECTED status: error, cause is RuntimeError: True")
    return passed


def main() -> int:
    r1 = check_default()
    r2 = check_rollback()
    r3 = check_fail()
    all_ok = r1 and r2 and r3
    print("RESULT:", "FIXED-OPT-IN (actionErrorPolicy, default=continue)" if all_ok else "NOT-FIXED/PARTIAL")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
