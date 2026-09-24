# -*- coding: utf-8 -*-
"""R5-05: `strict_targets=False` reopens the #108 root-target hole verbatim.

#108 rejects a transition targeting the machine root at build time. The
documented escape hatch `strict_targets=False` is for *unresolvable* targets
("these transitions will be silent no-ops at runtime"), but it skips the root
check wholesale. A root target RESOLVES -- to a node that cannot be a leaf --
so taking it empties the configuration while `status` stays "running",
`last_transition_ok` stays True and `last_error` stays None, on BOTH engines.
The empty configuration then snapshots and restores cleanly.

Standalone: stdlib + xstate_statemachine only.
"""
from __future__ import annotations

import asyncio
import json
import logging
import warnings

warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    XStateMachineError,
    create_machine,
)

CFG = {"id": "m", "initial": "a", "states": {"a": {"on": {"GO": "#m"}}, "b": {}}}


def mk():
    return create_machine(
        json.loads(json.dumps(CFG)), logic=MachineLogic(), strict_targets=False
    )


def sync_case() -> bool:
    it = SyncInterpreter(mk()).start()
    print("  sync before GO:", sorted(it.current_state_ids))
    it.send("GO")
    ids = sorted(it.current_state_ids)
    status, ok = it.status, it.last_transition_ok
    print(f"  sync after  GO: states={ids} status={it.status} "
          f"last_transition_ok={it.last_transition_ok} "
          f"last_error={type(it.last_error).__name__ if it.last_error else None}")
    snap = it.get_persisted_snapshot()
    print(f"  sync snapshot : configuration={snap.get('configuration')} "
          f"state_ids={snap.get('state_ids')} status={snap.get('status')}")
    try:
        r = SyncInterpreter.from_snapshot(json.dumps(snap), mk())
        print(f"  sync restored : states={sorted(r.current_state_ids)} status={r.status}")
        restored_inert = not r.current_state_ids
    except XStateMachineError as exc:
        print(f"  sync restored : refused with typed {type(exc).__name__}")
        restored_inert = False
    it.send("GO")
    print(f"  sync further send accepted; states={sorted(it.current_state_ids)}")
    it.stop()
    # Defect present when the configuration emptied while reporting healthy.
    return not ids and status == "running" and ok and restored_inert


async def async_case() -> bool:
    i = Interpreter(mk())
    await i.start()
    await i.send("GO", wait=True)
    await asyncio.sleep(0.05)
    ids = sorted(i.current_state_ids)
    print(f"  async after GO: states={ids} status={i.status} "
          f"last_transition_ok={i.last_transition_ok} "
          f"last_error={type(i.last_error).__name__ if i.last_error else None}")
    bad = not ids and i.status == "running" and i.last_transition_ok
    await i.stop()
    return bad


def main() -> int:
    bad_sync = sync_case()
    bad_async = asyncio.run(asyncio.wait_for(async_case(), 30))
    print()
    print("OBSERVED: with strict_targets=False a root target empties the "
          f"configuration silently (sync_defect={bad_sync}, async_defect={bad_async}).")
    print("EXPECTED: the #108 root-target rejection is unconditional (it is a "
          "configuration-legality rule, not a target-resolution one); failing "
          "that, taking it must set last_transition_ok=False with a typed "
          "last_error and must never leave zero active leaves while 'running'.")
    print("RESULT:", "FAIL" if (bad_sync or bad_async) else "PASS")
    return 1 if (bad_sync or bad_async) else 0


if __name__ == "__main__":
    raise SystemExit(main())
