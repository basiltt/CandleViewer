"""LC-19 verification on xstate-statemachine 0.8.0.

CHANGELOG [wave 3 / #44]: "from_snapshot(restart_services=True) and
pending_invocations() -- restoring a snapshot is still a static rebuild that
starts nothing by default, but pending_invocations() now lists every
PendingInvocation(...) ... and restart_services=True re-invokes each of them
from scratch."

This is an OPT-IN fix: default from_snapshot() behaviour is UNCHANGED (still
parks the machine); restart_services=True must now re-invoke. Tests both.
"""

from __future__ import annotations

import asyncio
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine

calls = {"place": 0, "entry": 0}


async def place(interp, ctx, evt):  # noqa: ANN001
    calls["place"] += 1
    await asyncio.sleep(5)
    return {"ok": True}


def on_entry(interp, ctx, evt, action):  # noqa: ANN001
    calls["entry"] += 1


CFG = {
    "id": "o",
    "initial": "submitting",
    "states": {
        "submitting": {
            "entry": ["on_entry"],
            "invoke": {"id": "place", "src": "place", "onDone": "submitted"},
        },
        "submitted": {},
    },
}
LOGIC = MachineLogic(actions={"on_entry": on_entry}, services={"place": place})


async def main() -> int:
    interp = await Interpreter(create_machine(CFG, logic=LOGIC)).start()
    await asyncio.sleep(0.1)
    snapshot = interp.get_snapshot()
    await interp.stop()
    print(f"OBSERVED pre-crash : state={sorted(interp.current_state_ids)} "
          f"place_calls={calls['place']} entry_calls={calls['entry']}")

    # --- default: no restart_services -> still parked (pin the existing default)
    calls["place"] = calls["entry"] = 0
    restored_default = Interpreter.from_snapshot(snapshot, create_machine(CFG, logic=LOGIC))
    pend_before_start = restored_default.pending_invocations()
    await restored_default.start()
    await asyncio.sleep(0.3)
    pend_after_start = restored_default.pending_invocations()
    print(f"OBSERVED default   : state={sorted(restored_default.current_state_ids)} "
          f"place_calls={calls['place']} entry_calls={calls['entry']} "
          f"status={restored_default.status!r} "
          f"pending_before_start={pend_before_start} pending_after_start={pend_after_start}")
    default_still_parked = calls["place"] == 0 and len(pend_before_start) == 1
    await restored_default.stop()

    # --- opt-in restart_services=True -> service restarted
    calls["place"] = calls["entry"] = 0
    restored = Interpreter.from_snapshot(
        snapshot, create_machine(CFG, logic=LOGIC), restart_services=True
    )
    await restored.start()
    await asyncio.sleep(0.3)
    pend_after_restart = restored.pending_invocations()
    print(f"OBSERVED restart_services=True: state={sorted(restored.current_state_ids)} "
          f"place_calls={calls['place']} entry_calls={calls['entry']} "
          f"status={restored.status!r} pending_invocations={pend_after_restart}")
    restart_reinvokes = calls["place"] >= 1
    pending_empty_after_restart = len(pend_after_restart) == 0
    entry_not_rerun = calls["entry"] == 0
    await restored.stop()

    print(f"EXPECTED default preserves 0.7.x parked behaviour: {default_still_parked}")
    print(f"EXPECTED restart_services=True reinvokes the service: {restart_reinvokes}")
    print(f"EXPECTED pending_invocations() empty after restart: {pending_empty_after_restart}")
    print(f"EXPECTED entry actions NOT re-run (per XState semantics): {entry_not_rerun}")

    ok = (
        default_still_parked
        and restart_reinvokes
        and pending_empty_after_restart
        and entry_not_rerun
    )
    return 0 if ok else 1


sys.exit(asyncio.run(main()))
