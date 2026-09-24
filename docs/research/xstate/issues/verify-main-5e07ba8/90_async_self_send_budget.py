"""Verify #90 on main@5e07ba8: async action-side `send()` is budgeted.

Acceptance criteria (from `gh issue view 90`):
  1. `c14_async_no_send_budget.py`, inverted to assert boundedness, exits 0
     on both engines.
  2. `test_async_action_self_send_is_bounded` (or the documentation variant)
     exists and pins the contract (library's
     `TestAsyncSelfSendBudget.test_action_side_send_loop_is_bounded` covers
     this).
  3. The engine-parity test is extended beyond the `raise` built-in.
  4. If a budget was added: `status` / a hook / a counter makes the trip
     observable (not a silent stop).

This script checks both the awaited (`await i.send(...)`) and fire-and-forget
(`i.send(...)` not awaited, mirroring the original C14 repro) action-side
self-send shapes, on the async engine, and confirms observability (
`last_transition_ok`, `last_error`, `on_event_dropped(reason="chain_budget")`).
"""
import asyncio
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import RunawayChainError

failures = []

CFG = {
    "id": "runaway",
    "initial": "run",
    "context": {"n": 0},
    "maxIterations": 200,
    "states": {"run": {"on": {"LOOP": {"actions": ["spin"]}}}},
}


# --- Shape A: awaited action-side send ("await i.send(...)") --------------
async def spin_awaited(i, c, e, a):
    c["n"] += 1
    await i.send("LOOP")


async def check_awaited():
    dropped = []

    class Plugin:
        def on_event_dropped(self, interp, event, reason):
            dropped.append(reason)

    m = create_machine(CFG, logic=MachineLogic(actions={"spin": spin_awaited}))
    i = Interpreter(m)
    i.use(Plugin())
    await i.start()
    await i.send("LOOP")
    await asyncio.sleep(0.5)
    n1 = i.context["n"]
    await asyncio.sleep(0.5)
    n2 = i.context["n"]
    ok = i.last_transition_ok
    err = i.last_error
    status = i.status
    await i.stop()

    if n2 > n1:
        failures.append(
            f"awaited-send: chain still growing after budget window "
            f"(n1={n1}, n2={n2}) -- unbounded"
        )
    if n1 > 202:
        failures.append(
            f"awaited-send: chain grew far past max_iterations+overhead: {n1}"
        )
    if ok:
        failures.append(
            "awaited-send: last_transition_ok is True after a chain-budget "
            "trip -- not observable"
        )
    if not isinstance(err, RunawayChainError):
        failures.append(
            f"awaited-send: last_error is not RunawayChainError: {err!r}"
        )
    if "chain_budget" not in dropped:
        failures.append(
            f"awaited-send: on_event_dropped(reason='chain_budget') never "
            f"fired: {dropped}"
        )
    if status != "running":
        failures.append(
            f"awaited-send: machine did not stay 'running' after the trip "
            f"(status={status!r}) -- a trip must not kill the machine"
        )


# --- Shape B: fire-and-forget action-side send (not awaited), the exact
#     shape of the original C14 repro -----------------------------------
def spin_fire_and_forget(i, c, e, a):
    c["n"] += 1
    i.send("LOOP")  # not awaited -- schedules a task/queues internally


async def check_fire_and_forget():
    m = create_machine(
        CFG, logic=MachineLogic(actions={"spin": spin_fire_and_forget})
    )
    i = Interpreter(m)
    await i.start()
    await i.send("LOOP")
    await asyncio.sleep(1.0)
    n2 = i.context["n"]
    await asyncio.sleep(1.0)
    n3 = i.context["n"]
    await i.stop()

    if n3 > n2:
        failures.append(
            f"fire-and-forget: chain still growing (n2={n2}, n3={n3}) -- "
            "async engine's non-awaited action-side send() is unbounded"
        )
    if n2 > 202:
        failures.append(
            f"fire-and-forget: chain grew far past max_iterations+overhead: "
            f"{n2}"
        )


async def main():
    await check_awaited()
    await check_fire_and_forget()


asyncio.run(main())

if failures:
    print("FAILURES:")
    for f in failures:
        print(" -", f)
    sys.exit(1)
print("ALL PASS")
