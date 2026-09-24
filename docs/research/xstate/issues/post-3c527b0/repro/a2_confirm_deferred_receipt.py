"""A2-confirm — receipt semantics for a DEFERRED event (main@5327ba6).

Claim under test: `send(E, wait=True)` under `onUnhandled: "defer"` resolves
the receipt as soon as the event is DEFERRED, reporting changed=False and
error=None -- i.e. "processed, nothing happened" -- even though the event is
parked and WILL later drive a transition when replayed.
"""

from __future__ import annotations

import asyncio
import warnings

from xstate_statemachine import Interpreter, MachineLogic, create_machine

warnings.simplefilter("ignore", DeprecationWarning)

CFG = {
    "id": "gate",
    "initial": "closed",
    "context": {"filled": 0},
    "onUnhandled": "defer",
    "states": {
        "closed": {"on": {"OPEN": "open"}},
        "open": {"on": {"FILL": {"target": "filled", "actions": ["mark"]}}},
        "filled": {},
    },
}


def mark(i, c, e, a):
    c["filled"] += 1


async def main() -> None:
    i = Interpreter(create_machine(CFG, logic=MachineLogic(actions={"mark": mark})))
    await i.start()

    # FILL arrives while still "closed" -> deferred (this is the LC-03 fix).
    receipt = await asyncio.wait_for(i.send("FILL", wait=True), timeout=3.0)
    print("receipt at defer time:")
    print("  changed =", receipt.changed)
    print("  error   =", receipt.error)
    print("  states  =", sorted(receipt.state_ids))
    print("  context =", i.context)
    print("  deferred_count =", i.deferred_count)

    assert receipt.changed is False
    assert receipt.error is None
    assert i.deferred_count == 1

    # The very same event is replayed later and DOES change everything.
    await i.send("OPEN")
    await asyncio.sleep(0.1)
    print("\nafter OPEN (replay):")
    print("  states  =", sorted(i.current_state_ids))
    print("  context =", i.context)
    await i.stop()

    assert "gate.filled" in i.current_state_ids
    assert i.context["filled"] == 1
    print(
        "\nCONFIRMED: the receipt said 'no change, no error' for an event that\n"
        "was neither dropped nor processed -- it was parked, and later drove\n"
        "the transition the caller had already been told did not happen."
    )


if __name__ == "__main__":
    asyncio.run(main())
