"""STANDALONE repro — DE-L1: the documented #219 `ensure_future` escape hatch
is refused, because the guard rides an INHERITABLE ContextVar.

Library @ de2da4e (unreleased 0.8.1; __version__ still reports 0.8.0).
stdlib + xstate_statemachine only. Every helper inlined. Run from ANY cwd.

Exit 1 == DEFECT REPRODUCED.
"""

import asyncio
import contextvars
import sys

from xstate_statemachine import create_machine, Interpreter
from xstate_statemachine.machine_logic import MachineLogic

CONFIG = {
    "id": "de",
    "initial": "x",
    "states": {
        "x": {"entry": ["kick"], "on": {"GO": "y"}},
        "y": {},
    },
}

WATCHDOG = 10.0


async def _case(spawn, label):
    """Returns (outcome, final_state)."""
    box = {"outcome": None}

    async def worker(interp):
        # The machine is long idle by now; the run loop is NOT in a step,
        # so no deadlock is possible on this await.
        await asyncio.sleep(0.30)
        try:
            await interp.send("GO", wait=True)
            box["outcome"] = "OK"
        except Exception as exc:  # noqa: BLE001
            box["outcome"] = type(exc).__name__

    holder = {}

    async def kick(interp, ctx, event, action_def):  # entry action
        spawn(holder, worker, interp)

    logic = MachineLogic(actions={"kick": kick})
    machine = create_machine(CONFIG, logic=logic)
    interp = Interpreter(machine)
    await asyncio.wait_for(interp.start(), timeout=WATCHDOG)

    deadline = asyncio.get_running_loop().time() + 5.0
    while box["outcome"] is None and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.02)  # poll to convergence

    state = sorted(interp.current_state_ids)
    await interp.stop()
    print(f"  {label:<46} -> {box['outcome']!r}, state={state}")
    return box["outcome"], state


def _spawn_inherited(holder, worker, interp):
    """The idiom `interpreters.md` prescribes."""
    holder["t"] = asyncio.ensure_future(worker(interp))


def _spawn_fresh_context(holder, worker, interp):
    """The workaround: a FRESH context, so _ACTIVE_ACTION_OWNER is unset."""
    ctx = contextvars.Context()
    holder["t"] = ctx.run(asyncio.ensure_future, worker(interp))

# --------------------------------------------------------------------------
# LANE B -- the documented idiom itself, when the spawning action yields.
# `interpreters.md` prescribes `asyncio.ensure_future(i.send(..., wait=True))`
# and "await it later". If the action awaits anything at all afterwards, the
# wrapper task runs WHILE the action is still on the stack and is refused.
# --------------------------------------------------------------------------


async def _lane_b(action_yields, label):
    """Returns (outcome, final_state)."""
    box = {}

    async def kick(interp, ctx, event, action_def):  # entry action
        box["h"] = asyncio.ensure_future(interp.send("GO", wait=True))
        if action_yields:
            await asyncio.sleep(0.05)  # ANY further await flips the outcome

    logic = MachineLogic(actions={"kick": kick})
    machine = create_machine(CONFIG, logic=logic)
    interp = Interpreter(machine)
    await asyncio.wait_for(interp.start(), timeout=WATCHDOG)

    try:
        await asyncio.wait_for(box["h"], timeout=5.0)
        outcome = "OK"
    except Exception as exc:  # noqa: BLE001
        outcome = type(exc).__name__

    state = sorted(interp.current_state_ids)
    await interp.stop()
    print(f"  {label:<46} -> {outcome!r}, state={state}")
    return outcome, state


async def main():
    print("DE-L1 — background worker spawned inside an action, sends 300ms AFTER idle")
    print("The machine is quiescent when the send happens; no deadlock is possible.\n")

    inherited, st_inherited = await _case(_spawn_inherited, "ensure_future (documented idiom)")
    fresh, st_fresh = await _case(_spawn_fresh_context, "ensure_future in a FRESH context")

    print()
    print("LANE B -- the documented idiom, await-it-later, action returns vs yields")
    print("Same idiom; the only difference is whether the action awaits afterwards.")
    print()

    no_yield, st_no_yield = await _lane_b(False, "ensure_future, action returns at once")
    yielded, st_yielded = await _lane_b(True, "ensure_future, action then awaits 50ms")

    print()
    lane_a = inherited == "ReentrantWaitError" and fresh == "OK"
    lane_b = no_yield == "OK" and yielded == "ReentrantWaitError"
    print(f"A: documented idiom refused after idle : {inherited == 'ReentrantWaitError'}")
    print(f"A: fresh-context control works         : {fresh == 'OK'}")
    print(f"A: machine advanced (idiom / control)  : {st_inherited == ['de.y']} / {st_fresh == ['de.y']}")
    print(f"B: idiom OK when the action returns    : {no_yield == 'OK'}")
    print(f"B: SAME idiom refused when it yields   : {yielded == 'ReentrantWaitError'}")
    print(f"B: machine advanced (returns / yields) : {st_no_yield == ['de.y']} / {st_yielded == ['de.y']}")

    reproduced = lane_a and lane_b
    print()
    print(f"REPRODUCED (both lanes): {reproduced}")
    return 1 if reproduced else 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(asyncio.wait_for(main(), timeout=30.0)))
    except asyncio.TimeoutError:
        print("WATCHDOG: hung")
        sys.exit(2)
