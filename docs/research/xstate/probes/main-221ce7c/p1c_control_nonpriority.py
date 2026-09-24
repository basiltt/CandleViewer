"""L-1 probe: does an EXTERNAL send(priority=True) get charged to the
chain budget when it lands while a macrostep is in flight?

_deliver_priority() increments _raise_depth whenever self._processing is
True, with no test for who issued the event. send(..., priority=True) is a
public external API. If an outside producer outruns the loop, its events
are counted as self-generated and dropped at max_iterations -- the exact
"5,000 legitimate sends lost 3,999" failure the run-loop architecture note
says the design exists to avoid.
"""

import asyncio

from xstate_statemachine import Interpreter, MachineLogic, create_machine

CONFIG = {
    "id": "p1",
    "initial": "a",
    "context": {"n": 0},
    "states": {
        "a": {"on": {"PING": {"actions": ["bump"]}}},
    },
}


async def bump(interp, ctx, ev, action_def):  # noqa: ANN001
    ctx["n"] += 1
    # Yield inside the macrostep so a concurrent producer can run while
    # _processing is True. This is an ordinary `await` in user code.
    await asyncio.sleep(0)


class Watch:
    def __init__(self) -> None:
        self.dropped = []

    def on_event_dropped(self, i, e, reason):  # noqa: ANN001
        self.dropped.append((e.type, reason))

    def __getattr__(self, _n):  # every other hook is a no-op
        return lambda *a, **k: None


async def main() -> None:
    m = create_machine(CONFIG, logic=MachineLogic(actions={"bump": bump}))
    w = Watch()
    interp = Interpreter(m)
    interp._plugins.append(w)
    await interp.start()

    N = 3000  # > default max_iterations (1000)

    async def producer() -> None:
        for _ in range(N // 10):
            for _ in range(10):  # burst: the lane never empties
                interp.send("PING")
            await asyncio.sleep(0)

    await producer()
    for _ in range(200):
        if interp.context["n"] >= N or w.dropped:
            break
        await asyncio.sleep(0.005)
    await asyncio.sleep(0.05)

    print(f"sent={N} processed={interp.context['n']}")
    print(f"dropped={len(w.dropped)} reasons={set(r for _, r in w.dropped)}")
    print(f"_raise_depth={interp._raise_depth} tripped={interp._chain_tripped}")
    print(f"last_error={type(interp.last_error).__name__}")
    print(
        "VERDICT:",
        (
            "EXTERNAL PRIORITY SENDS DROPPED AS SELF-GENERATED"
            if w.dropped
            else "no drops"
        ),
    )
    await interp.stop()


asyncio.run(main())
