"""LC-03 verification on xstate-statemachine 0.8.0.

Issue: events with no handler vanished with no trace (0.7.0). 0.8.0 fix:
per-machine `onUnhandled: "ignore" | "defer" | "error"` policy. Default
"ignore" preserves 0.7.x drop semantics but is now OBSERVABLE via
`on_unhandled_event`. `defer` (library-owned) replays at the head of the
queue, in original order, ahead of live traffic, and survives snapshot
restore; bounded by DEFER_MAX.

Checks:
  1. DEFAULT ("ignore"): event still dropped silently (0.7.x state/behaviour
     preserved) but now observable through on_unhandled_event.
  2. OPT-IN "error": UnhandledEventError raised, status == "error".
  3. OPT-IN "defer": the filer's exact repro scenario -- 3 events arrive
     before ACK, all replay after ACK, ending at ['oms.filled'] with
     filled == 30 (issue's acceptance criteria verbatim).

Exit 0 if all three behave per spec, 1 otherwise.
"""

from __future__ import annotations

import logging
import sys
from typing import Any, Dict, List

from xstate_statemachine import (
    MachineLogic,
    SyncInterpreter,
    UnhandledEventError,
    create_machine,
)
from xstate_statemachine.plugins import PluginBase

logging.disable(logging.CRITICAL)


def _oms(policy: str = None) -> Dict[str, Any]:
    cfg: Dict[str, Any] = {
        "id": "oms",
        "initial": "idle",
        "context": {"filled": 0, "seen": []},
        "states": {
            "idle": {"on": {"NEW": "submitting"}},
            "submitting": {"on": {"ACK": "live"}},
            "live": {
                "on": {
                    "PARTIAL": {"actions": ["apply"]},
                    "FILL": {"target": "filled", "actions": ["apply"]},
                }
            },
            "filled": {"type": "final"},
        },
    }
    if policy is not None:
        cfg["onUnhandled"] = policy
    return cfg


def _logic() -> MachineLogic:
    def apply(i, c, e, a):
        c["filled"] += e.payload["qty"]
        c["seen"].append(e.payload["qty"])

    return MachineLogic(actions={"apply": apply})


class Spy(PluginBase):
    def __init__(self) -> None:
        self.unhandled: List[Any] = []

    def on_unhandled_event(self, interp, event, active, disposition):
        self.unhandled.append((event.type, sorted(active), disposition))


def check_default_ignore() -> bool:
    spy = Spy()
    i = SyncInterpreter(create_machine(_oms(), logic=_logic()))
    i.use(spy)
    i.start()
    i.send("NEW")
    i.send({"type": "PARTIAL", "qty": 10})

    print(
        "DEFAULT OBSERVED filled:", i.context["filled"],
        "state:", sorted(i.current_state_ids),
        "status:", i.status,
        "unhandled hook:", spy.unhandled,
    )
    passed = (
        i.context["filled"] == 0
        and sorted(i.current_state_ids) == ["oms.submitting"]
        and i.status == "running"
        and spy.unhandled == [("PARTIAL", ["oms.submitting"], "ignored")]
    )
    print("DEFAULT EXPECTED filled: 0, state: ['oms.submitting'], status: running, unhandled: observable via hook")
    return passed


def check_error_policy() -> bool:
    i = SyncInterpreter(create_machine(_oms("error"), logic=_logic()))
    i.start()
    i.send("NEW")
    i.send({"type": "PARTIAL", "qty": 10})

    print("ERROR OBSERVED status:", i.status, "error:", type(i.error).__name__)
    passed = i.status == "error" and isinstance(i.error, UnhandledEventError)
    print("ERROR EXPECTED status: error, error: UnhandledEventError")
    return passed


def check_defer_policy() -> bool:
    i = SyncInterpreter(create_machine(_oms("defer"), logic=_logic()))
    i.start()
    i.send("NEW")
    i.send({"type": "PARTIAL", "qty": 10})
    i.send({"type": "PARTIAL", "qty": 10})
    i.send({"type": "FILL", "qty": 10})
    print("DEFER OBSERVED (pre-ACK) filled:", i.context["filled"], "deferred_count:", i.deferred_count)
    i.send("ACK")

    state = sorted(i.current_state_ids)
    filled = i.context["filled"]
    print("DEFER OBSERVED (post-ACK) state:", state, "filled:", filled, "deferred_count:", i.deferred_count)
    passed = state == ["oms.filled"] and filled == 30 and i.deferred_count == 0
    print("DEFER EXPECTED state: ['oms.filled'], filled: 30, deferred_count: 0")
    return passed


def main() -> int:
    r1 = check_default_ignore()
    r2 = check_error_policy()
    r3 = check_defer_policy()
    all_ok = r1 and r2 and r3
    print(
        "RESULT:",
        "FIXED-OPT-IN (onUnhandled, default=ignore)" if all_ok else "NOT-FIXED/PARTIAL",
    )
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
