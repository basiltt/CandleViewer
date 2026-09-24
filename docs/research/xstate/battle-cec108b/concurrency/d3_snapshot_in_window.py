"""D-concurrency-3 (minimal): a snapshot taken while an async action is
awaiting persists an EMPTY configuration; restoring it yields a machine
that reports `status == "running"` and responds to nothing, forever.

Mechanism
---------
`_execute_transition` (base_interpreter.py:2278-2345) performs
exit -> actions -> enter as one "transaction". The comment at :2340 is
explicit about why:

    ATOMICITY: exit -> actions -> enter is ONE transaction. If a user
    action raises in the middle, the source has been left and the target
    never reached, so the configuration would be EMPTY while `status`
    still read "running" -- permanently dead and reporting itself
    healthy.

The rollback handles the FAILURE case. It does not handle the
OBSERVATION case: the transaction is not atomic with respect to the
event loop. The moment any transition action does `await`, the run-loop
task suspends with `_active_state_nodes` already emptied by
`_exit_states` and not yet repopulated by `_enter_states`. Every other
task on that loop -- an HTTP health endpoint, a metrics scraper, a
periodic snapshotter -- sees exactly the state the comment calls
"permanently dead and reporting itself healthy":

    current_state_ids   == set()
    active_state_ids    == set()
    matches(<anything>) == False
    status              == "running"
    get_persisted_snapshot()["state_ids"]  == []
    get_persisted_snapshot()["status"]     == "running"

The window is not a scheduling hairline: it lasts exactly as long as the
action awaits (measured 0.252 s for a 0.25 s await, 17/17 samples empty).
Any `await` inside an action -- an HTTP call, a DB write, an
`asyncio.sleep` -- opens it.

The snapshot is the part that turns a transient observation into durable
corruption, which is what this repro demonstrates: persist during the
window, restore, and the machine is inert.

Run:
    python d3_snapshot_in_window.py
"""

from __future__ import annotations

import asyncio
import json

from xstate_statemachine import Interpreter, MachineLogic, create_machine

GATE: dict = {}

CFG = {
    "id": "order",
    "initial": "submitted",
    "context": {"fills": 0},
    "states": {
        "submitted": {
            "on": {"ACK": {"target": "working", "actions": ["notify_venue"]}}
        },
        "working": {"on": {"FILL": {"actions": ["record_fill"]}}},
    },
}


async def notify_venue(interpreter, ctx, event, action_def):  # noqa: ANN001
    """Any awaiting action: an HTTP call to the venue, a DB write, ..."""
    GATE["entered"].set()
    await GATE["release"].wait()


def record_fill(interpreter, ctx, event, action_def):  # noqa: ANN001
    ctx["fills"] += 1


def machine():
    return create_machine(
        CFG,
        logic=MachineLogic(
            actions={"notify_venue": notify_venue, "record_fill": record_fill}
        ),
    )


async def main() -> int:
    GATE["entered"] = asyncio.Event()
    GATE["release"] = asyncio.Event()

    live = Interpreter(machine())
    await live.start()
    print("before          :", sorted(live.current_state_ids), live.status)

    async def trigger():
        await live.send("ACK")

    t = asyncio.create_task(trigger())
    await asyncio.wait_for(GATE["entered"].wait(), 5)

    # --- a concurrent snapshotter runs here; nothing tells it not to ---
    snap = live.get_persisted_snapshot()
    print("during window   :", sorted(live.current_state_ids), live.status)
    print("  matches('submitted'):", live.matches("submitted"))
    print("  matches('working')  :", live.matches("working"))
    print("  snapshot state_ids  :", snap["state_ids"])
    print("  snapshot status     :", snap["status"])

    GATE["release"].set()
    await t
    await asyncio.sleep(0.05)
    print("after           :", sorted(live.current_state_ids), live.status)
    await live.stop()

    # --- the process restarts and restores that snapshot ---
    GATE["entered"] = asyncio.Event()
    GATE["release"] = asyncio.Event()
    GATE["release"].set()
    restored = Interpreter.from_snapshot(json.dumps(snap), machine())
    await restored.start()
    print("\nrestored        :", sorted(restored.current_state_ids), restored.status)
    r = await asyncio.wait_for(restored.send("FILL", wait=True), 5)
    print("  FILL receipt changed:", r.changed, "error:", repr(r.error))
    print("  context             :", dict(restored.context))
    print("  states              :", sorted(restored.current_state_ids))
    print("  status              :", restored.status)
    dead = not restored.current_state_ids and restored.status == "running"
    await restored.stop()

    print(
        "\nRESULT:",
        "FAIL - restored machine has no configuration, status 'running', "
        "and ignores every event"
        if dead
        else "PASS",
    )
    return 1 if dead else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
