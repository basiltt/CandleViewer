"""R10-06 (STANDALONE): #209's "all three lanes agree at limits 1-25" is false
on engine-work-only charts, and the gap GROWS with the limit.

The chart below has no timers and no delayed sends, so the #206 carve-out
(timer-paced self-sends are caller-`tick()`-driven on `SyncInterpreter`) does
not apply -- every step is engine work the chain budget is DEFINED to charge.
The two engines nevertheless charge the `always` settle step differently
relative to `raise`: async grows ~3*mi+3, sync ~2*mi+3.

Both lanes DO trip with RunawayChainError at every limit, so nothing runs away.
The defect is the overstated GUARANTEE: the runaway budget is a safety control,
and a downstream reader sizing `maxIterations` against a worst-case work bound
will rely on cross-engine equivalence. At mi=25 the same chart is permitted
~47% more work on one engine than on the other.

Exit 0 = every swept limit agrees across lanes (claim holds).
Exit 1 = any limit differs (claim overstated).

Stdlib + xstate_statemachine only. Runs from any cwd. Watchdog 90 s.
"""
from __future__ import annotations

import asyncio
import json
import sys

from xstate_statemachine import (
    create_machine,
    Interpreter,
    SyncInterpreter,
    MachineLogic,
)

LIMITS = (1, 3, 5, 10, 15, 19, 25)


def _cfg(mi: int) -> dict:
    # `always` bounces a <-> b; each entry raises, so every lap is engine work.
    return {
        "id": "w",
        "initial": "a",
        "maxIterations": mi,
        "states": {
            "a": {
                "entry": [{"type": "raise", "params": {"event": "GO"}}, "tick"],
                "on": {"GO": "b"},
            },
            "b": {"always": "a", "entry": ["tick"]},
        },
    }


def _machine(mi: int, counter: dict):
    def _tick(i, c, e, a=None):
        counter["n"] += 1

    return create_machine(
        json.loads(json.dumps(_cfg(mi))), logic=MachineLogic(actions={"tick": _tick})
    )


async def _async_laps(mi: int) -> tuple:
    c = {"n": 0}
    interp = Interpreter(_machine(mi, c))
    await interp.start()
    # Poll to convergence rather than sampling: stable count over 5 x 60 ms.
    last, stable = -1, 0
    for _ in range(60):
        await asyncio.sleep(0.06)
        if c["n"] == last:
            stable += 1
            if stable >= 5:
                break
        else:
            last, stable = c["n"], 0
    err = type(getattr(interp, "last_error", None)).__name__
    await interp.stop()
    return c["n"], err


def _sync_laps(mi: int) -> tuple:
    c = {"n": 0}
    interp = SyncInterpreter(_machine(mi, c))
    interp.start()
    err = type(getattr(interp, "last_error", None)).__name__
    interp.stop()
    return c["n"], err


async def main() -> int:
    diff = 0
    print(f"{'maxIter':<10}{'sync':<10}{'async':<10}{'agree':<8}errors")
    for mi in LIMITS:
        a, aerr = await _async_laps(mi)
        s, serr = _sync_laps(mi)
        ok = a == s
        diff += 0 if ok else 1
        print(f"{mi:<10}{s:<10}{a:<10}{('yes' if ok else 'NO'):<8}"
              f"sync={serr} async={aerr}")
    print()
    print("VERDICT:", "CLAIM OVERSTATED" if diff else "ok",
          f"({diff}/{len(LIMITS)} swept limits differ)")
    return 1 if diff else 0


if __name__ == "__main__":
    try:
        rc = asyncio.run(asyncio.wait_for(main(), 90.0))
    except asyncio.TimeoutError:
        print("WATCHDOG TIMEOUT")
        rc = 1
    sys.exit(rc)
