"""G-19: a child that FAILS at (approximately) the moment the parent exits
the invoking state. Does a stale `onError` land in the state we just left?

RESULT: no. `_cancel_state_tasks` detaches the completion listener before
stopping the child, so the later failure is suppressed. Scanned across the
race window in 1 ms steps; `p.aborted` every time."""
import asyncio
from xstate_statemachine import MachineLogic, create_machine
from xstate_statemachine.interpreter import Interpreter

DELAY = {"v": 0.02}

async def blow(i, c, e):
    await asyncio.sleep(DELAY["v"])
    raise ValueError("boom")

CHILD = {"id": "c", "initial": "w",
         "states": {"w": {"invoke": {"src": "inner", "id": "inner"}}}}
PARENT = {"id": "p", "initial": "work", "states": {
    "work": {"invoke": {"src": "kid", "id": "kid", "onError": {"target": "failed"}},
             "on": {"ABORT": "aborted"}},
    "failed": {}, "aborted": {}}}

async def run(child_fail_at, abort_at):
    DELAY["v"] = child_fail_at
    ch = create_machine(CHILD, logic=MachineLogic(services={"inner": blow}))
    m = create_machine(PARENT, logic=MachineLogic(services={"kid": ch}))
    it = await Interpreter(m).start()
    await asyncio.sleep(abort_at)
    await it.send("ABORT")
    await asyncio.sleep(0.25)
    r = (set(it.current_state_ids), it.status, len(it._actors),
         len(it._invoked_children), len(asyncio.all_tasks()))
    await it.stop()
    return r

async def main():
    # Control: no ABORT at all -- onError must fire.
    DELAY["v"] = 0.02
    ch = create_machine(CHILD, logic=MachineLogic(services={"inner": blow}))
    m = create_machine(PARENT, logic=MachineLogic(services={"kid": ch}))
    it = await Interpreter(m).start(); await asyncio.sleep(0.3)
    print("CONTROL (no abort):", set(it.current_state_ids), "(expect p.failed)")
    await it.stop()
    print()
    for abort_at in [0.018, 0.019, 0.020, 0.021, 0.022, 0.025]:
        r = await run(0.020, abort_at)
        flag = "  <-- STALE onError" if "p.failed" in r[0] else ""
        print(f"child_fails_at=20.0ms abort_at={abort_at*1000:5.1f}ms -> "
              f"state={r[0]} status={r[1]} actors={r[2]} invoked={r[3]} "
              f"tasks={r[4]}{flag}")

asyncio.run(main())
