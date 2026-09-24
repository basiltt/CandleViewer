"""L-4 probe: an EXTERNAL event arriving mid-chain resets the settle budget,
so a modest external event rate defeats the per-macrostep `always` bound.

The reset is unconditional at the top of each iteration:
    if not is_system_event(event) or from_inbox:
        self._settle_iterations = 0
An `always` livelock is settled INSIDE one macrostep, so an external event
cannot interleave there -- but a chain made of `always` + completion hops
CAN be interleaved, and each external event hands it a fresh allowance.
This probe measures total microsteps executed under a steady external
drip vs. the declared maxIterations.
"""

import asyncio

from xstate_statemachine import Interpreter, MachineLogic, create_machine

CONFIG = {
    "id": "p4",
    "initial": "ver",
    "context": {"laps": 0},
    "maxIterations": 20,
    "states": {
        "ver": {"always": {"target": "arm"}, "on": {"NOISE": {}}},
        "arm": {
            "invoke": {
                "src": "svc",
                "id": "svc",
                "onDone": {"target": "ver", "actions": ["lap"]},
            },
            "on": {"NOISE": {}},
        },
    },
}


def lap(interp, ctx, ev, action_def):  # noqa: ANN001
    ctx["laps"] += 1


def svc(interp, ctx, ev):  # noqa: ANN001
    return 1


async def run(noise: bool) -> None:
    m = create_machine(
        CONFIG, logic=MachineLogic(actions={"lap": lap}, services={"svc": svc})
    )
    interp = Interpreter(m)
    await interp.start()
    for _ in range(100):  # ~5 s ceiling
        if noise:
            interp.send("NOISE")  # ordinary external traffic
        await asyncio.sleep(0.05)
        if interp.context["laps"] > 3000:
            break
    laps = interp.context["laps"]
    tripped = interp._settle_tripped or interp._chain_tripped
    print(
        f"[noise={noise}] laps={laps} settle_tripped={interp._settle_tripped} "
        f"chain_tripped={interp._chain_tripped} "
        f"VERDICT={'BOUNDED at ~20' if tripped and laps < 100 else 'BUDGET RENEWED BY EXTERNAL TRAFFIC'}"
    )
    try:
        await asyncio.wait_for(interp.stop(), timeout=3)
    except Exception:  # noqa: BLE001
        print(f"[noise={noise}] stop() timed out")


async def main() -> None:
    await run(noise=False)
    await run(noise=True)


asyncio.run(main())
