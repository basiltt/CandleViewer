"""Q7b - MINIMAL: a machine whose invoke cycle has tripped never answers
an external event again while it is driven.

From Q7: 100 of 200 soak machines failed to answer `send("PING",
wait=True)` within 5 s, and it was exactly the 100 machines of the two
self-re-arming invoke shapes (`rollback_ondone`, `invoke_pingpong`). The
`always`/plain machines all answered.

Mechanism (and why this is the operational face of q1b/q1c): every
external event resets the per-macrostep budget, so the machine re-enters
the cycle for another `maxIterations` laps BEFORE the next inbox event is
read. With any inbound traffic the inbox is never drained faster than the
cycle re-arms, so `send(wait=True)` never resolves. The machine is not
crashed -- `status` is `running`, CPU is pinned at ~1 core -- it is
permanently unresponsive.

Single machine, no threads. Bounded by a 20 s watchdog.
"""

from __future__ import annotations

import asyncio
import time

from common import emit
from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import RunawayChainError

LAPS = {"n": 0}


def act(i, ctx, e, ad):  # noqa: ANN001
    LAPS["n"] += 1


def svc(i, ctx, e):  # plain def -> executor  # noqa: ANN001
    time.sleep(0.001)
    return {"v": 1}


def cfg(shape: str) -> dict:
    if shape == "invoke_pingpong":
        states = {
            "ver": {
                "invoke": {
                    "src": "exec",
                    "onDone": {"target": "arm", "actions": ["act"]},
                    "onError": {"target": "arm"},
                }
            },
            "arm": {
                "always": {"target": "ver", "actions": ["act"]},
                "on": {"PING": {"actions": ["act"]}},
            },
        }
    else:  # always_cycle control -- expected to stay responsive
        states = {
            "ver": {
                "always": {"target": "arm", "actions": ["act"]},
                "on": {"PING": {"actions": ["act"]}},
            },
            "arm": {
                "always": {"target": "ver", "actions": ["act"]},
                "on": {"PING": {"actions": ["act"]}},
            },
        }
    return {
        "id": "q7b",
        "initial": "ver",
        "context": {"n": 0},
        "maxIterations": 50,
        "states": states,
    }


def mk(shape: str):
    return create_machine(
        cfg(shape),
        logic=MachineLogic(actions={"act": act}, services={"exec": svc}),
    )


async def case(shape: str, driven: bool) -> dict:
    LAPS["n"] = 0
    itp = Interpreter(mk(shape), service_pool_size=2)
    await asyncio.wait_for(itp.start(), 10)
    await asyncio.sleep(0.3)
    tripped = isinstance(itp.last_error, RunawayChainError)

    stop = asyncio.Event()

    async def driver() -> None:
        while not stop.is_set():
            try:
                itp.send_threadsafe("PING")
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(0.005)

    d = asyncio.create_task(driver()) if driven else None
    t0 = time.perf_counter()
    try:
        await asyncio.wait_for(itp.send("PING", wait=True), 10)
        answered = True
    except asyncio.TimeoutError:
        answered = False
    probe_s = round(time.perf_counter() - t0, 2)
    stop.set()
    if d:
        d.cancel()
        try:
            await d
        except asyncio.CancelledError:
            pass
    status = itp.status
    laps = LAPS["n"]
    try:
        await asyncio.wait_for(itp.stop(), 10)
        stopped = "ok"
    except asyncio.TimeoutError:
        stopped = "HUNG"
    return {
        "shape": shape,
        "driven_by_external_traffic": driven,
        "tripped_before_probe": tripped,
        "external_probe_answered": answered,
        "probe_seconds": probe_s,
        "laps_burned": laps,
        "status": status,
        "stop": stopped,
    }


PLAIN = {
    "id": "plain",
    "initial": "idle",
    "context": {"n": 0},
    "states": {"idle": {"on": {"PING": {"actions": ["act"]}}}},
}


def mk_plain():
    return create_machine(PLAIN, logic=MachineLogic(actions={"act": act}))


async def storm(name: str, factory, n: int, seconds: float) -> dict:
    """n machines of one shape, driven at ~4000 PING/s for `seconds`,
    then every machine is probed concurrently with a 5 s deadline."""
    import random

    LAPS["n"] = 0
    itps = [factory() for _ in range(n)]
    await asyncio.gather(*(i.start() for i in itps))
    t0 = time.perf_counter()
    sent = 0
    depth_trace = []
    while time.perf_counter() - t0 < seconds:
        for _ in range(200):
            try:
                random.choice(itps).send_threadsafe("PING")
                sent += 1
            except Exception:  # noqa: BLE001
                pass
        await asyncio.sleep(0.05)
        if len(depth_trace) < 12:
            depth_trace.append(sum(i.queue_depth for i in itps))

    async def probe(i):  # noqa: ANN001
        try:
            await asyncio.wait_for(i.send("PING", wait=True), 5)
            return 0
        except asyncio.TimeoutError:
            return 1
        except Exception:  # noqa: BLE001
            return 0

    wedged = sum(await asyncio.gather(*(probe(i) for i in itps)))
    backlog = sum(i.queue_depth for i in itps)
    statuses = sorted({i.status for i in itps})
    try:
        await asyncio.wait_for(
            asyncio.gather(*(i.stop() for i in itps)), 30
        )
        stopped = "ok"
    except asyncio.TimeoutError:
        stopped = "HUNG"
    return {
        "shape": name,
        "machines": n,
        "seconds_driven": seconds,
        "events_sent": sent,
        "inbox_backlog_trace_per_0.05s": depth_trace,
        "final_inbox_backlog": backlog,
        "machines_not_answering_in_5s": wedged,
        "statuses": statuses,
        "laps_burned": LAPS["n"],
        "stop": stopped,
    }


async def main() -> int:
    single = [
        await case("invoke_pingpong", False),
        await case("invoke_pingpong", True),
    ]
    storms = [
        await storm("plain(control)", lambda: Interpreter(mk_plain()), 10, 6),
        await storm(
            "always_cycle(control)",
            lambda: Interpreter(mk("always_cycle"), service_pool_size=2),
            10,
            6,
        ),
        await storm(
            "invoke_pingpong",
            lambda: Interpreter(mk("invoke_pingpong"), service_pool_size=2),
            10,
            6,
        ),
    ]
    bad = [s for s in storms if s["machines_not_answering_in_5s"]]
    emit(
        "q7b_minimal_invoke_cycle_unresponsive",
        {
            "single_machine_is_fine": single,
            "under_sustained_load": storms,
            "shapes_that_wedged": [
                (s["shape"], s["machines_not_answering_in_5s"],
                 s["final_inbox_backlog"])
                for s in bad
            ],
            "result": "FAIL" if bad else "PASS",
        },
    )
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
