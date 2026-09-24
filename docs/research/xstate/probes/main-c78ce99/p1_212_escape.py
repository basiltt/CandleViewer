"""P-1/P-2 (#212): what is NOT charged any more.

STANDALONE: stdlib + xstate_statemachine only. Run from any cwd.

A) mixed chart: delayed raise -> entry zero-delay raise -> delayed raise.
   Does the per-period chain reset let it run past maxIterations for ever?
B) sub-millisecond delay: `raise(delay=0.0001)` is truthy, so it takes the
   TIMER path (uncharged) while waiting ~0 s. Compare the lap RATE against
   `delay=0` (falsy -> zero-delay raise -> charged, trips).
"""

import asyncio
import time
from typing import Any, Dict

from xstate_statemachine import Interpreter, MachineLogic, create_machine

LIMIT = 10


def _mk(cfg: Dict[str, Any]) -> Any:
    def bump(i: Any, c: Any, e: Any, a: Any) -> None:
        c["n"] += 1

    async def abump(i: Any, c: Any, e: Any, a: Any) -> None:
        c["n"] += 1

    return create_machine(
        cfg, logic=MachineLogic(actions={"beat": bump, "abeat": abump})
    )


def mixed_cfg(act: str, delay: Any) -> Dict[str, Any]:
    """A: state A arms a DELAYED self-raise; TICK -> B; B raises GO with NO
    delay (same-step work); GO -> A. Every period contains real zero-delay
    chain work, but the delay arming resets the chain each period."""
    return {
        "id": "mix",
        "initial": "A",
        "maxIterations": LIMIT,
        "context": {"n": 0},
        "states": {
            "A": {
                "entry": [
                    {
                        "type": "raise",
                        "params": {"event": "TICK", "delay": delay},
                    },
                    act,
                ],
                "on": {"TICK": "B"},
            },
            "B": {
                "entry": [{"type": "raise", "params": {"event": "GO"}}, act],
                "on": {"GO": "A"},
            },
        },
    }


def pure_cfg(act: str, delay: Any) -> Dict[str, Any]:
    arm = {"type": "raise", "params": {"event": "BEAT", "delay": delay}}
    if delay == 0:
        arm = {"type": "raise", "params": {"event": "BEAT"}}
    return {
        "id": "hb",
        "initial": "up",
        "maxIterations": LIMIT,
        "context": {"n": 0},
        "states": {
            "up": {"entry": [arm, act], "on": {"BEAT": "down"}},
            "down": {"entry": [arm, act], "on": {"BEAT": "up"}},
        },
    }


async def run(cfg: Dict[str, Any], window: float) -> Any:
    i = await Interpreter(_mk(cfg)).start()
    t0 = time.perf_counter()
    await asyncio.sleep(window)
    el = time.perf_counter() - t0
    n = i.context["n"]
    err = type(i.last_error).__name__ if i.last_error else None
    await i.stop()
    return n, err, round(n / el, 1)


async def main() -> None:
    for act in ("beat", "abeat"):
        print(f"--- action kind: {act} ---")
        for label, cfg, w in (
            ("A mixed delayed+zero-delay (delay=1)", mixed_cfg(act, 1), 1.0),
            ("A mixed (delay=0.0001)", mixed_cfg(act, 0.0001), 0.5),
            ("B pure raise(delay=1)", pure_cfg(act, 1), 1.0),
            ("B pure raise(delay=0.0001)", pure_cfg(act, 0.0001), 0.5),
            ("B pure raise(delay=0) [control]", pure_cfg(act, 0), 0.5),
        ):
            n, err, rate = await run(cfg, w)
            print(
                f"  {label:42s} beats={n:6d} err={err} rate={rate}/s "
                f"(limit={LIMIT})"
            )


if __name__ == "__main__":
    asyncio.run(main())
