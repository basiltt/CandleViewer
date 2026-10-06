"""Verify #125 on main@cec108b: on SyncInterpreter, a deferred event's
replay runs as its OWN macrostep -- the triggering event's Receipt is final
(reflects only the triggering event's own transition) before any replay
runs.
"""
from __future__ import annotations
import sys as _xs_sys  # noqa: E402
from pathlib import Path as _XsPath  # noqa: E402
_xs_sys.path.insert(0, str(_XsPath(__file__).resolve().parents[2] / "gate"))
from _paths import REPO_ROOT as _REPO, XSTATE_SRC as _XS, upstream_main_python as _xs_main_py  # noqa: E402,F401

import sys

sys.path.insert(
    0, str(_XS / 'src')
)

from xstate_statemachine import MachineLogic, SyncInterpreter, create_machine  # noqa: E402

failures = []


def check(name, cond):
    print(f"[{'OK' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


CFG = {
    "id": "m",
    "initial": "a",
    "onUnhandled": "defer",
    "states": {
        "a": {"on": {"ARM": "b"}},
        "b": {"on": {"LATE": "c"}},
        "c": {},
    },
}


def main() -> int:
    i = SyncInterpreter(create_machine(CFG, logic=MachineLogic())).start()
    late_receipt = i.send("LATE", wait=True)
    check("LATE's own receipt reports deferred=True", late_receipt.deferred is True)

    arm_receipt = i.send("ARM", wait=True)
    check(
        "ARM's receipt reflects only ARM's own transition (state 'b')",
        set(arm_receipt.state_ids) == {"m.b"},
    )
    check(
        "the replay DID run, right after, as its own step",
        i.current_state_ids == {"m.c"},
    )

    # send_events / tick also run held replays (test_send_events_and_tick_also_run_held_replays)
    i2 = SyncInterpreter(create_machine(CFG, logic=MachineLogic())).start()
    i2.send_events(["LATE", "ARM"])
    check("send_events also runs held replays", i2.current_state_ids == {"m.c"})

    return 0 if not failures else 1


if __name__ == "__main__":
    rc = main()
    print(f"\nRESULT: {'PASS' if rc == 0 else 'FAIL'} ({len(failures)} failing)")
    sys.exit(rc)
