"""L-9 probe: an `after` timer that comes due WHILE a macrostep is in
flight is charged to the chain budget.

`_after_timer._fire` calls `_deliver_priority(fired)`, which now does
`if self._processing: self._raise_depth += 1`. Wall-clock time passing is
not the machine feeding itself -- and the docstring on `_deliver_priority`
explicitly claims "a due timer firing on an idle loop ... is free", but
the loop is NOT idle whenever a macrostep awaits (any `async def` action,
any coroutine service, any child `sendTo`). So a periodic machine whose
steps await accumulates budget from its own clock.
"""

import asyncio

from xstate_statemachine import Interpreter, MachineLogic, create_machine

CONFIG = {
    "id": "p9",
    "initial": "tick",
    "context": {"ticks": 0},
    "maxIterations": 100,
    "states": {
        "tick": {
            "after": {"1": {"target": "tock", "actions": ["count"]}},
            "on": {"X": {"actions": ["slow"]}},
        },
        "tock": {"after": {"1": {"target": "tick", "actions": ["count"]}},
                 "on": {"X": {"actions": ["slow"]}}},
    },
}


def count(interp, ctx, ev, action_def):  # noqa: ANN001
    ctx["ticks"] += 1


async def slow(interp, ctx, ev, action_def):  # noqa: ANN001
    # An ordinary awaiting action: the loop turns, timers fire, but
    # `_processing` is True the whole time.
    await asyncio.sleep(0.004)


class Watch:
    def __init__(self):
        self.dropped = []

    def on_event_dropped(self, i, e, reason):  # noqa: ANN001
        self.dropped.append((e.type, reason))

    def __getattr__(self, _n):
        return lambda *a, **k: None


async def main() -> None:
    m = create_machine(
        CONFIG, logic=MachineLogic(actions={"count": count, "slow": slow})
    )
    w = Watch()
    i = Interpreter(m)
    i._plugins.append(w)
    await i.start()

    # Drive ordinary awaiting work so `_processing` is usually True.
    for _ in range(400):
        i.send("X")
        await asyncio.sleep(0.002)
        if w.dropped:
            break
    await asyncio.sleep(0.1)

    print(f"ticks={i.context['ticks']} raise_depth={i._raise_depth} "
          f"chain_tripped={i._chain_tripped}")
    after_drops = [t for t, r in w.dropped if r == "chain_budget"]
    print(f"chain_budget drops={len(after_drops)} sample={after_drops[:5]}")
    print(
        "VERDICT:",
        "AFTER TIMERS / EXTERNAL WORK CHARGED AND DROPPED"
        if after_drops
        else "no drops in this window",
    )
    try:
        await asyncio.wait_for(i.stop(), timeout=3)
    except Exception:  # noqa: BLE001
        print("stop() timed out")


asyncio.run(main())
