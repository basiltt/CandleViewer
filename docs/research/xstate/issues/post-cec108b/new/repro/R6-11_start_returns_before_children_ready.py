"""R6-11: `await Interpreter.start()` returns before the initial macrostep
has finished settling -- specifically, before invoke-children declared in
the initial entry set are registered in the actor system, and before an
initial plain-`def` service has a chance to complete its handoff.

Root cause (per the draft): `start()` (interpreter.py ~487-496) calls
`_enter_states` + `_settle_transient_transitions` but never calls
`_await_inline_services()`, which is otherwise only reached from the run
loop (interpreter.py ~1645/1649). So the executor handoff future created in
`_start_service` (interpreter.py ~2417-2425) is first drained by the FIRST
event's macrostep, not by `start()` itself.

`SyncInterpreter.start()` does not have this async handoff at all, so the
two engines disagree about what "started" means.

Run: python R6-11_start_returns_before_children_ready.py
Expect (bug present): the machine is still in its pre-completion state
  (`parent.running`) immediately after `await start()` returns, even though
  the initial invoke's plain-`def` service body has already run; the
  `done.invoke` transition to `parent.done` only lands a few ms later, once
  some other await point drains `_await_inline_services()`.
"""
import asyncio
import sys
import time

from xstate_statemachine import Interpreter, MachineLogic, create_machine


completed = {"n": False}


def child_service(interpreter, context, event):
    # A cheap plain-`def` service, invoked from the INITIAL entry set.
    completed["n"] = True
    return {"ok": True}


CFG = {
    "id": "parent",
    "initial": "running",
    "states": {
        "running": {
            "invoke": {
                "id": "kid",
                "src": "child_service",
                "onDone": {"target": "done"},
            },
        },
        "done": {"type": "final"},
    },
}


async def main():
    m = create_machine(CFG, logic=MachineLogic(services={"child_service": child_service}))
    i = Interpreter(m)

    t0 = time.monotonic()
    await i.start()
    t_start = (time.monotonic() - t0) * 1000
    completed_immediately_after_start = completed["n"]
    state_immediately_after_start = sorted(i.current_state_ids)

    # Poll until the machine actually reaches "done" (i.e. the run loop has
    # processed `done.invoke` for the initial invoke), to measure the gap
    # `start()` left un-awaited.
    deadline = time.monotonic() + 1.0
    while "parent.done" not in i.current_state_ids and time.monotonic() < deadline:
        await asyncio.sleep(0.001)
    gap_ms = (time.monotonic() - t0) * 1000 - t_start
    reached_done_eventually = "parent.done" in i.current_state_ids

    print(f"start() took {t_start:.1f} ms")
    print(
        f"state right after start() returned: {state_immediately_after_start} "
        f"(service body already ran: {completed_immediately_after_start})"
    )
    print(
        f"reached 'done' eventually: {reached_done_eventually} "
        f"(~{gap_ms:.1f} ms after start() returned); "
        f"final state={sorted(i.current_state_ids)}"
    )

    await i.stop()

    bug_present = (
        state_immediately_after_start != ["parent.done"]
    ) and reached_done_eventually
    if bug_present:
        print(
            "BUG CONFIRMED: await start() returned before the initial "
            "macrostep's inline service settled -- the machine was still "
            "in its pre-completion state when start() handed control back."
        )
        sys.exit(1)
    else:
        print("Not reproduced: the initial service had already completed when start() returned.")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
