"""R5-01 repro: `SnapshotMidStepError` (#102) uses an *any-leaf* test, so a
parallel machine whose one region is mid-transition still snapshots — with the
whole region missing — and restores as a half-dead machine reporting healthy.

Stdlib + xstate_statemachine only. Exits 1 while present, 0 once fixed.
"""

import asyncio
import json
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import SnapshotMidStepError

CFG = {
    "id": "ord",
    "type": "parallel",
    "context": {},
    "states": {
        "exchange": {
            "initial": "working",
            "states": {
                "working": {"on": {"FILL": {"target": "filled", "actions": ["slow"]}}},
                "filled": {},
            },
        },
        "risk": {"initial": "checking", "states": {"checking": {}}},
    },
}


async def slow(interpreter, ctx, event, action_def):
    # A realistic awaiting transition action (DB write / exchange call).
    await asyncio.sleep(0.4)


def logic():
    return MachineLogic(actions={"slow": slow})


async def main() -> int:
    live = await Interpreter(create_machine(CFG, logic=logic())).start()
    task = live.send("FILL")
    await asyncio.sleep(0.15)  # inside the exchange region's macrostep

    refused = None
    snap = None
    try:
        snap = live.get_persisted_snapshot()
    except SnapshotMidStepError as exc:
        refused = type(exc).__name__

    await task
    await asyncio.sleep(0.05)
    await live.stop()

    print("OBSERVED:")
    print("  snapshot refused          :", refused)
    if snap is not None:
        blob = json.dumps(snap)
        doc = json.loads(blob)
        print("  snapshot state_ids        :", doc.get("state_ids"))
        print("  snapshot configuration    :", doc.get("configuration"))
        restored = await Interpreter.from_snapshot(
            blob, create_machine(CFG, logic=logic())
        ).start()
        r_fill = await restored.send("FILL", wait=True)
        print("  restored current_state_ids:", sorted(restored.current_state_ids))
        print("  restored status           :", restored.status)
        print("  restored FILL receipt     :", r_fill)
        await restored.stop()

    print("EXPECTED:")
    print("  SnapshotMidStepError, or a configuration with exactly one active")
    print("  leaf per parallel region (both 'ord.exchange.*' and 'ord.risk.*')")

    if refused is None:
        cfg = set(json.loads(json.dumps(snap)).get("configuration") or [])
        torn = not any(c.startswith("ord.exchange.") for c in cfg)
        if torn:
            print("RESULT: FAIL - region 'ord.exchange' absent from an accepted snapshot")
            return 1
    print("RESULT: PASS")
    return 0


sys.exit(asyncio.run(main()))
