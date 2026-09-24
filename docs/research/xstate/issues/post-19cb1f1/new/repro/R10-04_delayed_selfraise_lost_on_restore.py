"""R10-04 (STANDALONE): an armed-but-unfired delayed self-`raise` has no
snapshot representation and is silently lost on restore.

`_snapshot_pending_events` (interpreter.py:1480-1497) reads the priority queue
plus the inbox deque only, so a timer that is ARMED but has not yet FIRED has no
representation in the snapshot at all -- unlike a *fired* `after`, which #107
persists via the priority lane. #206 made the delayed self-send a debt of the
arming step; a snapshot discharges that debt with no hook, no warning and no
error. Restore does not re-run entry actions, so the machine resumes into a
state whose ONLY exit was the lost event.

Part B: an EXTERNAL delayed send survives -- the asymmetry is the finding.

Exit 0 = the restored machine progresses like the live one (fixed).
Exit 1 = the restored machine is wedged while the live one progressed (defect).

Stdlib + xstate_statemachine only. Runs from any cwd. Watchdog 40 s.
"""
from __future__ import annotations

import asyncio
import json
import sys

from xstate_statemachine import create_machine, Interpreter, MachineLogic

CFG = {
    "id": "debt",
    "initial": "a",
    "states": {
        # The ONLY exit from `a` is the delayed self-raise armed on entry.
        "a": {
            "entry": [{"type": "raise", "params": {"event": "PONG", "delay": 300}}],
            "on": {"PONG": "b"},
        },
        "b": {},
    },
}


def _build(kind: str):
    def _noop(i, c, e, a=None):
        return None

    async def _noop_async(i, c, e, a=None):
        return None

    fn = _noop if kind == "def" else _noop_async
    return create_machine(
        json.loads(json.dumps(CFG)), logic=MachineLogic(actions={"noop": fn})
    )


async def run(kind: str) -> dict:
    # --- live lane: arm, wait past the delay, observe progress -------------
    live = Interpreter(_build(kind))
    await live.start()
    await asyncio.sleep(0.05)          # 50 ms into the 300 ms window
    snap = live.get_persisted_snapshot()
    pend = list(snap.get("pending_events") or [])
    defr = list(snap.get("deferred_events") or [])
    await asyncio.sleep(0.60)          # well past the 300 ms delay
    live_states = sorted(live.current_state_ids)
    await live.stop()

    # --- restored lane: same blob, same wall clock ------------------------
    rest = Interpreter.from_snapshot(json.dumps(snap), _build(kind))
    await rest.start()
    await asyncio.sleep(0.60)
    rest_states = sorted(rest.current_state_ids)
    await rest.stop()

    return {
        "pending_in_snapshot": pend,
        "deferred_in_snapshot": defr,
        "live": live_states,
        "restored": rest_states,
    }


async def main() -> int:
    bad = 0
    for kind in ("def", "async def"):
        r = await run(kind)
        lost = r["live"] != r["restored"]
        print(f"[{kind}] snapshot pending_events={r['pending_in_snapshot']} "
              f"deferred={r['deferred_in_snapshot']}")
        print(f"[{kind}] live after 650ms  = {r['live']}")
        print(f"[{kind}] restored after 600ms = {r['restored']}"
              f"   {'<-- DEBT LOST' if lost else ''}")
        bad += 1 if lost else 0
    print()
    print("VERDICT:", "DEFECT PRESENT" if bad else "ok", f"({bad}/2 kinds)")
    return 1 if bad else 0


if __name__ == "__main__":
    try:
        rc = asyncio.run(asyncio.wait_for(main(), 40.0))
    except asyncio.TimeoutError:
        print("WATCHDOG TIMEOUT")
        rc = 1
    sys.exit(rc)
