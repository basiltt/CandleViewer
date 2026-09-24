"""R2 - `_chain_owed` under 100 concurrent NEVER-completing coroutine
services, then `stop()`.

#179 introduced `_chain_owed`: a step that armed a coroutine service keeps
its chain open until the completion lands. The debt is settled by
`_publish_completion` or by the task being CANCELLED. Attack: arm 100
services that never return, then exit the state / stop the machine.

Checks:
  * does `_chain_owed` return to 0 after every owning state is exited?
  * does `stop()` hang?
  * does a leaked debt poison the chain-budget accounting afterwards, i.e.
    does an `always` cycle still trip at its documented lap count?
  * both `def` (executor, NOT cancellable) and `async def` (task).

Bounded: 20 s watchdog on every stop.
"""

from __future__ import annotations

import asyncio
import time

from common2 import Interpreter, MachineLogic, create_machine, emit
from xstate_statemachine.exceptions import RunawayChainError

N = 100
LAPS = {"n": 0}
STOPFLAG = {"go": False}


def act(i, ctx, e, ad):  # noqa: ANN001
    LAPS["n"] += 1


async def never_async(i, ctx, e):  # noqa: ANN001
    await asyncio.sleep(3600)


def never_def(i, ctx, e):  # runs on the executor; not cancellable  # noqa: ANN001
    while not STOPFLAG["go"]:
        time.sleep(0.01)
    return {"v": 1}


def cfg() -> dict:
    """One state invoking a never-completing service; LEAVE exits it, then
    an always-cycle that must still trip at maxIterations."""
    return {
        "id": "r2",
        "initial": "hold",
        "context": {"n": 0},
        "maxIterations": 50,
        "states": {
            "hold": {
                "invoke": {
                    "src": "never",
                    "onDone": {"target": "cyc"},
                    "onError": {"target": "cyc"},
                },
                "on": {"LEAVE": {"target": "idle"}},
            },
            "idle": {"on": {"CYCLE": {"target": "cyc"}}},
            "cyc": {
                "always": {"target": "cyc2", "actions": ["act"]},
            },
            "cyc2": {"always": {"target": "cyc", "actions": ["act"]}},
        },
    }


def mk(kind: str):
    svc = never_async if kind == "async def" else never_def
    return create_machine(
        cfg(), logic=MachineLogic(actions={"act": act}, services={"never": svc})
    )


def owed(i) -> int:  # noqa: ANN001
    return getattr(i, "_chain_owed", -1)


async def case(kind: str) -> dict:
    STOPFLAG["go"] = False
    LAPS["n"] = 0
    itps = [Interpreter(mk(kind), service_pool_size=8) for _ in range(N)]
    t0 = time.perf_counter()
    try:
        await asyncio.wait_for(asyncio.gather(*(i.start() for i in itps)), 60)
        started = True
    except asyncio.TimeoutError:
        started = False
    start_s = round(time.perf_counter() - t0, 2)
    await asyncio.sleep(0.3)
    owed_armed = sorted({owed(i) for i in itps})

    # Exit every owning state -> every armed service's debt must settle.
    for i in itps:
        i.send_threadsafe("LEAVE")
    await asyncio.sleep(0.6)
    owed_after_exit = sorted({owed(i) for i in itps})

    # Does the budget still work after the exit? Drive one machine's cycle.
    probe = itps[0]
    LAPS["n"] = 0
    try:
        await asyncio.wait_for(probe.send("CYCLE", wait=True), 10)
        cycle_wedged = False
    except asyncio.TimeoutError:
        cycle_wedged = True
    await asyncio.sleep(0.3)
    laps = LAPS["n"]
    tripped = isinstance(probe.last_error, RunawayChainError)

    t1 = time.perf_counter()
    STOPFLAG["go"] = True
    try:
        await asyncio.wait_for(asyncio.gather(*(i.stop() for i in itps)), 30)
        stopped = "ok"
    except asyncio.TimeoutError:
        stopped = "HUNG"
    stop_s = round(time.perf_counter() - t1, 2)
    owed_final = sorted({owed(i) for i in itps})
    leftover = len([t for t in asyncio.all_tasks() if not t.done()]) - 1
    return {
        "service_kind": kind,
        "machines": N,
        "start_ok": started,
        "start_seconds": start_s,
        "chain_owed_while_armed": owed_armed,
        "chain_owed_after_state_exit": owed_after_exit,
        "chain_owed_after_stop": owed_final,
        "cycle_after_exit_wedged": cycle_wedged,
        "cycle_laps": laps,
        "cycle_tripped_observably": tripped,
        "stop": stopped,
        "stop_seconds": stop_s,
        "leftover_tasks": leftover,
        "statuses": sorted({i.status for i in itps}),
    }


async def main() -> int:
    rows = [await case(k) for k in ("async def", "def")]
    bad = []
    for r in rows:
        if r["stop"] != "ok":
            bad.append((r["service_kind"], "stop hung"))
        if r["chain_owed_after_state_exit"] != [0]:
            bad.append(
                (r["service_kind"], f"owed leak {r['chain_owed_after_state_exit']}")
            )
        if r["cycle_after_exit_wedged"]:
            bad.append((r["service_kind"], "cycle wedged after exit"))
        if not r["cycle_tripped_observably"]:
            bad.append((r["service_kind"], "cycle trip not observable"))
    emit(
        "r2_chain_owed_never_completing",
        {"rows": rows, "failures": bad, "result": "FAIL" if bad else "PASS"},
    )
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
