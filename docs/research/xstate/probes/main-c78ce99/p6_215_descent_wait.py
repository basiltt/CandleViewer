"""P-6 (#215): can `start()` hang on a non-terminating initial descent?

STANDALONE, 25 s watchdog -- a TIMEOUT IS THE RESULT.

#215 made the run loop `await self._descent_done.wait()` before consuming
anything. `_descent_done.set()` happens in `start()`'s try-body and again in
`finally`. Question: is there any descent shape where `start()` itself does
not return -- an `always` self-cycle in the initial state, or an entry
action that awaits an event only the run loop could deliver?

  a) `always` cycle in the initial configuration (settle budget should cut)
  b) entry action awaits a receipt for an event it sends to itself: the run
     loop is parked on `_descent_done`, which only `start()` sets -> deadlock?
  c) seed standing: does a descent `raise` chain now get MORE laps than a
     post-start one at the same maxIterations?
"""

import asyncio
from typing import Any, Dict

from xstate_statemachine import Interpreter, MachineLogic, create_machine

WATCHDOG = 25.0


def _mk(cfg: Dict[str, Any], **acts: Any) -> Any:
    return create_machine(cfg, logic=MachineLogic(actions=acts))


async def guarded(name: str, coro: Any) -> None:
    try:
        print(f"{name}: {await asyncio.wait_for(coro, WATCHDOG)}")
    except asyncio.TimeoutError:
        print(f"{name}: *** TIMEOUT after {WATCHDOG}s -- start() never returned")
    except Exception as exc:  # noqa: BLE001
        print(f"{name}: {type(exc).__name__}: {str(exc)[:110]}")


# (a) always-cycle inside the initial configuration
A_CFG: Dict[str, Any] = {
    "id": "alw",
    "initial": "x",
    "maxIterations": 12,
    "context": {"n": 0},
    "states": {
        "x": {"entry": ["bump"], "always": {"target": "y"}},
        "y": {"entry": ["bump"], "always": {"target": "x"}},
    },
}


async def case_a() -> Any:
    def bump(i: Any, c: Any, e: Any, a: Any) -> None:
        c["n"] += 1

    i = Interpreter(_mk(A_CFG, bump=bump))
    await i.start()
    n = i.context["n"]
    err = type(i.last_error).__name__ if i.last_error else None
    await i.stop()
    return f"start() returned, n={n}, err={err}"


# (b) an async entry action that awaits a receipt for its own send
B_CFG: Dict[str, Any] = {
    "id": "dead",
    "initial": "x",
    "context": {"n": 0},
    "states": {"x": {"entry": ["selfwait"], "on": {"GO": "y"}}, "y": {}},
}


async def case_b() -> Any:
    async def selfwait(i: Any, c: Any, e: Any, a: Any) -> None:
        # a receipt can only resolve once the RUN LOOP processes the event,
        # and the run loop is parked on `_descent_done` until start() ends.
        await asyncio.wait_for(i.send("GO", wait=True), 5.0)
        c["n"] += 1

    i = Interpreter(_mk(B_CFG, selfwait=selfwait))
    await i.start()
    out = f"start() returned, n={i.context['n']}, states={sorted(i.current_state_ids)}"
    await i.stop()
    return out


# (c) descent raise chain vs post-start raise chain, same limit
def c_cfg(entry_raise: bool) -> Dict[str, Any]:
    arm = {"type": "raise", "params": {"event": "GO"}}
    return {
        "id": "seed",
        "initial": "a",
        "maxIterations": 6,
        "context": {"n": 0},
        "states": {
            "a": {
                "entry": ([arm] if entry_raise else []) + ["bump"],
                "on": {"GO": "b", "KICK": "b"},
            },
            "b": {"entry": [arm, "bump"], "on": {"GO": "a"}},
        },
    }


async def case_c() -> Any:
    def bump(i: Any, c: Any, e: Any, a: Any) -> None:
        c["n"] += 1

    async def laps(entry_raise: bool) -> int:
        i = await Interpreter(_mk(c_cfg(entry_raise), bump=bump)).start()
        if not entry_raise:
            await i.send("KICK")
        await asyncio.sleep(0.4)
        n = i.context["n"]
        await i.stop()
        return n

    return f"descent-seeded chain={await laps(True)} laps, external-seeded={await laps(False)} laps (limit=6)"


async def main() -> None:
    await guarded("a) always-cycle in descent  ", case_a())
    await guarded("b) entry awaits own receipt ", case_b())
    await guarded("c) seed standing lap counts ", case_c())


if __name__ == "__main__":
    asyncio.run(main())
