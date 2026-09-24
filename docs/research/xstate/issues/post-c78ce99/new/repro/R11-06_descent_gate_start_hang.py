"""R11-06 (STANDALONE): #215's `_descent_done` gate deadlocks `start()` forever,
silently, when an entry action awaits a receipt on its own interpreter.

#215 made `Interpreter._run_event_loop` `await self._descent_done.wait()` before
entering its main loop. `_descent_done` is set only at the END of `start()`'s
try-body. So an `async def` entry action that does
`await i.send("GO", wait=True)` cannot be satisfied: the receipt resolves only
when the run loop processes `GO`, and the run loop is parked on the gate, which
only the completion of that same entry action can open.

With no timeout in the user's action, `start()` NEVER RETURNS. It is silent:
`last_error is None`, status `running`, configuration legal -- indistinguishable
from a slow entry action.

Control A below is the correctly-bounded case: an `always` self-cycle in the
descent returns from `start()` with `RunawayChainError`. The settle budget DOES
cover the descent; only the receipt cycle hangs.

Exit 0 = start() returns within the bound (defect fixed).
Exit 1 = start() times out while the control returns.

Stdlib + xstate_statemachine only. Runs from any cwd. Watchdog 40 s.
"""
from __future__ import annotations

import asyncio
import sys

from xstate_statemachine import create_machine, Interpreter, MachineLogic

START_BOUND_S = 3.0


def hang_cfg() -> dict:
    return {
        "id": "dead",
        "initial": "x",
        "states": {
            "x": {"entry": ["await_own_receipt"], "on": {"GO": "y"}},
            "y": {},
        },
    }


def control_cfg() -> dict:
    """An `always` self-cycle in the descent -- bounded by the settle budget."""
    return {
        "id": "ctl",
        "initial": "x",
        "maxIterations": 12,
        "states": {
            "x": {"entry": ["bump"], "always": {"target": "x", "reenter": True}},
        },
    }


async def probe_hang() -> dict:
    holder: dict = {}

    async def await_own_receipt(i, c, e, a=None):  # noqa: ANN001  async def
        holder["interp"] = i
        # The receipt can only resolve once the run loop runs -- and the run
        # loop is waiting for THIS action to finish opening `_descent_done`.
        await i.send("GO", wait=True)

    machine = create_machine(
        hang_cfg(),
        logic=MachineLogic(actions={"await_own_receipt": await_own_receipt}),
    )
    interp = Interpreter(machine)

    loop = asyncio.get_running_loop()
    t0 = loop.time()
    timed_out = False
    try:
        await asyncio.wait_for(interp.start(), START_BOUND_S)
    except asyncio.TimeoutError:
        timed_out = True
    elapsed = round(loop.time() - t0, 2)

    out = {
        "start_timed_out": timed_out,
        "start_seconds": elapsed,
        "last_error": type(getattr(interp, "last_error", None)).__name__,
        "status": str(getattr(interp, "status", "?")),
        "states": list(getattr(interp, "current_state_ids", []) or []),
    }
    try:
        await asyncio.wait_for(interp.stop(), 2.0)
    except Exception:
        pass
    return out


async def probe_control() -> dict:
    n = {"i": 0}

    def bump(i, c, e, a=None):  # noqa: ANN001  plain def
        n["i"] += 1

    machine = create_machine(
        control_cfg(), logic=MachineLogic(actions={"bump": bump})
    )
    interp = Interpreter(machine)
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    timed_out = False
    try:
        await asyncio.wait_for(interp.start(), START_BOUND_S)
    except asyncio.TimeoutError:
        timed_out = True
    elapsed = round(loop.time() - t0, 2)
    out = {
        "start_timed_out": timed_out,
        "start_seconds": elapsed,
        "entries": n["i"],
        "last_error": type(getattr(interp, "last_error", None)).__name__,
    }
    try:
        await asyncio.wait_for(interp.stop(), 2.0)
    except Exception:
        pass
    return out


async def main() -> int:
    hang = await probe_hang()
    ctl = await probe_control()

    print("A) entry action awaits its own receipt (the defect)")
    for k, v in hang.items():
        print(f"     {k:<18}{v}")
    print()
    print("B) CONTROL: `always` self-cycle in the descent (settle budget)")
    for k, v in ctl.items():
        print(f"     {k:<18}{v}")
    print()

    reproduced = hang["start_timed_out"] and not ctl["start_timed_out"]
    print(f"start() hung           : {hang['start_timed_out']}")
    print(f"control returned bounded: {not ctl['start_timed_out']}")
    print(f"hang is SILENT         : {hang['last_error'] == 'NoneType'}")
    print(f"REPRODUCED: {reproduced}")
    return 1 if reproduced else 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(asyncio.wait_for(main(), 40)))
    except asyncio.TimeoutError:
        print("WATCHDOG: exceeded 40 s")
        sys.exit(2)
