"""N-02 repro: `SyncInterpreter` `after` deadlines are unreachable by `tick()`
when the interpreter is constructed inside a running asyncio loop.

`RealClock.set_timeout` branches on the *caller's* context, not on which engine
owns the clock: if a loop is running it parks the deadline on
`loop.call_later`, otherwise it pushes onto its own heap. `SyncInterpreter.tick()`
and the pump at the top of `send()` both drain only the heap. So a sync machine
built inside a running loop arms timers that its own API cannot deliver --
`tick()` stops being authoritative for a deadline that is genuinely due.

Control: the identical machine built on an off-loop thread fires correctly.

Exit 1 while the defect is present, 0 once it is fixed.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import threading
import time

from xstate_statemachine import SyncInterpreter, create_machine

logging.disable(logging.CRITICAL)

CFG = {
    "id": "sy",
    "initial": "a",
    "states": {"a": {"after": {40: "b"}}, "b": {}},
}

DELAY_S = 0.040
SETTLE_S = 0.120


def _drive() -> tuple[int, set[str]]:
    """Build, start, wait past the deadline, then tick once. Returns
    (clock.pending, states)."""
    interp = SyncInterpreter(create_machine(CFG))
    interp.start()
    time.sleep(SETTLE_S)  # the deadline is now unambiguously due
    pending = _pending(interp)
    interp.tick()
    states = set(interp.current_state_ids)
    try:
        interp.stop()
    except Exception:  # noqa: BLE001
        pass
    return pending, states


def _pending(interp: SyncInterpreter) -> int:
    clock = getattr(interp, "clock", None) or getattr(interp, "_clock", None)
    for attr in ("pending", "_heap"):
        val = getattr(clock, attr, None)
        if val is None:
            continue
        try:
            return int(val) if isinstance(val, int) else len(val)
        except TypeError:
            return len(getattr(val, "_items", []) or [])
    return -1


def off_loop() -> tuple[int, set[str]]:
    box: dict[str, tuple[int, set[str]]] = {}
    t = threading.Thread(target=lambda: box.update(r=_drive()))
    t.start()
    t.join(10)
    return box["r"]


async def main() -> int:
    ctrl_pending, ctrl_states = off_loop()

    # Subject: build + start + tick entirely on the loop's own thread, inside a
    # running loop. The sleep is a *blocking* sleep so no loop turn can slip in
    # and deliver the call_later callback -- the point is that tick() alone must
    # be sufficient.
    interp = SyncInterpreter(create_machine(CFG))
    interp.start()
    time.sleep(SETTLE_S)
    subj_pending = _pending(interp)
    interp.tick()
    subj_states = set(interp.current_state_ids)
    try:
        interp.stop()
    except Exception:  # noqa: BLE001
        pass

    print(f"OBSERVED off-loop control  : clock.pending={ctrl_pending} states={sorted(ctrl_states)}")
    print(f"OBSERVED in-running-loop   : clock.pending={subj_pending} states={sorted(subj_states)}")
    print("EXPECTED both              : clock.pending=1 before tick, states=['sy.b'] after")

    control_ok = "sy.b" in ctrl_states
    subject_ok = "sy.b" in subj_states
    if control_ok and not subject_ok:
        print("RESULT: DEFECT REPRODUCED")
        return 1
    if control_ok and subject_ok:
        print("RESULT: NOT REPRODUCED (fixed)")
        return 0
    print("RESULT: INCONCLUSIVE - the off-loop control did not fire either")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
