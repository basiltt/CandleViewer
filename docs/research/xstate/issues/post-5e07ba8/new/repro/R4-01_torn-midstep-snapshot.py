"""R4-01 repro: mid-macrostep snapshot is torn and restores as a permanently
inert machine that reports itself healthy.

Exits 1 while the defect is present, 0 once fixed.
Stdlib + xstate_statemachine only.
"""

import asyncio
import json
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine

CFG = {
    "id": "t",
    "initial": "a",
    "context": {},
    "states": {
        "a": {"on": {"GO": {"target": "b", "actions": ["slow"]}}},
        "b": {},
    },
}


async def slow(interpreter, ctx, event, action_def):
    # A realistic awaiting transition action: the exit->actions->enter
    # transaction is open for the whole of this sleep.
    await asyncio.sleep(0.4)


def logic():
    return MachineLogic(actions={"slow": slow})


async def main() -> int:
    live = Interpreter(create_machine(CFG, logic=logic()))
    await live.start()

    task = live.send("GO")
    await asyncio.sleep(0.15)  # we are now inside the transition window

    # Everything a health check can see says the machine is fine.
    healthy_probe = (live.status, live.queue_depth, live.is_running)

    snap = live.get_persisted_snapshot()
    blob = snap if isinstance(snap, str) else json.dumps(snap)
    doc = json.loads(blob)

    await task
    await asyncio.sleep(0.1)

    restored = Interpreter.from_snapshot(blob, create_machine(CFG, logic=logic()))
    await restored.start()
    receipt = await restored.send("PING", wait=True)

    print("OBSERVED:")
    print("  mid-window public probes  :", "status=%s queue_depth=%s is_running=%s" % healthy_probe)
    print("  snapshot state_ids        :", doc.get("state_ids"))
    print("  snapshot configuration    :", doc.get("configuration"))
    print("  snapshot status           :", doc.get("status"))
    print("  restored current_state_ids:", sorted(restored.current_state_ids))
    print("  restored status           :", restored.status)
    print("  restored dormant invokes  :", restored.has_dormant_invocations)
    print("  PING receipt              :", receipt)

    print("EXPECTED:")
    print("  snapshot state_ids        : non-empty (either ['t.a'] or ['t.b'])")
    print("  restored current_state_ids: non-empty, and PING is matched or")
    print("                              get_persisted_snapshot() refuses/awaits")
    print("                              while a macrostep is in flight")

    torn = not doc.get("state_ids")
    inert = not restored.current_state_ids and restored.status == "running"

    await restored.stop()
    await live.stop()

    if torn or inert:
        print("RESULT: FAIL - torn snapshot restores as a silently-inert machine")
        return 1
    print("RESULT: PASS")
    return 0


sys.exit(asyncio.run(main()))
