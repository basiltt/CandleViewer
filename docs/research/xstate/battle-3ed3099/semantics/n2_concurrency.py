"""N2 — CONCURRENCY attacks: #105 (per-task self-send gate) and #104
(BLOCK enqueues eagerly), under create_task fan-out, OS threads and a
child actor.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Dict, List

from n_harness import attack, main

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    OverflowPolicy,
    QueueOverflowError,
    create_machine,
)

COUNTER = {
    "id": "c",
    "initial": "up",
    "context": {"n": 0},
    "states": {"up": {"on": {"TICK": {"actions": ["inc"]}}}},
}


def _logic() -> MachineLogic:
    def inc(i, ctx, e, am):  # noqa: ANN001
        ctx["n"] = ctx.get("n", 0) + 1

    return MachineLogic(actions={"inc": inc})


@attack(
    "N2-01",
    "#105: 64 concurrent create_task producers are NOT charged to maxIterations",
    "external producers sending during an in-flight step must never trip the chain budget",
)
async def n2_01() -> Dict[str, Any]:
    cfg = dict(COUNTER)
    cfg["maxIterations"] = 25  # deliberately tiny: an external send must not count
    m = create_machine(cfg, logic=_logic())
    i = await Interpreter(m).start()
    P, K = 64, 20

    async def producer() -> None:
        for _ in range(K):
            await i.send("TICK")
            await asyncio.sleep(0)

    await asyncio.gather(*[producer() for _ in range(P)])
    for _ in range(80):
        await asyncio.sleep(0.01)
        if i.context["n"] >= P * K:
            break
    n = i.context["n"]
    err = str(i.last_error) if i.last_error else None
    status = i.status
    await i.stop()
    return {
        "ok": n == P * K and err is None and status == "running",
        "expected": P * K,
        "observed": n,
        "last_error": err,
        "status": status,
    }


@attack(
    "N2-02",
    "#105: 12 OS threads sending via send_threadsafe() are not charged either",
    "a gateway thread pool feeding an OMS must not trip the self-send gate",
)
async def n2_02() -> Dict[str, Any]:
    cfg = dict(COUNTER)
    cfg["maxIterations"] = 25
    m = create_machine(cfg, logic=_logic())
    i = await Interpreter(m).start()
    loop = asyncio.get_running_loop()
    T, K = 12, 25

    def worker() -> None:
        for _ in range(K):
            i.send_threadsafe("TICK")

    threads = [threading.Thread(target=worker) for _ in range(T)]
    for t in threads:
        t.start()
    while any(t.is_alive() for t in threads):
        await asyncio.sleep(0.01)
    for t in threads:
        t.join()
    for _ in range(100):
        await asyncio.sleep(0.01)
        if i.context["n"] >= T * K:
            break
    n = i.context["n"]
    err = str(i.last_error) if i.last_error else None
    await i.stop()
    return {
        "ok": n == T * K and err is None,
        "expected": T * K,
        "observed": n,
        "last_error": err,
    }


@attack(
    "N2-03",
    "#104: BLOCK under 16 concurrent producers loses no event and never deadlocks",
    "a lost fill under back-pressure is money loss; a deadlock is an outage",
)
async def n2_03() -> Dict[str, Any]:
    m = create_machine(COUNTER, logic=_logic())
    i = await Interpreter(
        m, max_queue_size=4, overflow_policy=OverflowPolicy.BLOCK
    ).start()
    P, K = 16, 25

    async def producer(pid: int) -> None:
        for _ in range(K):
            await i.send("TICK")

    try:
        await asyncio.wait_for(
            asyncio.gather(*[producer(p) for p in range(P)]), timeout=45
        )
        timed_out = False
    except asyncio.TimeoutError:
        timed_out = True
    for _ in range(300):
        await asyncio.sleep(0.01)
        if i.context["n"] >= P * K:
            break
    n = i.context["n"]
    err = str(i.last_error) if i.last_error else None
    await i.stop()
    return {
        "ok": (not timed_out) and n == P * K and err is None,
        "expected": P * K,
        "observed": n,
        "deadlocked": timed_out,
        "last_error": err,
    }


@attack(
    "N2-04",
    "#104: a fire-and-forget send() under BLOCK with room in the inbox is enqueued",
    "the exact #104 shape: an un-awaited-effect send on an empty inbox was lost",
)
async def n2_04() -> Dict[str, Any]:
    m = create_machine(COUNTER, logic=_logic())
    i = await Interpreter(
        m, max_queue_size=8, overflow_policy=OverflowPolicy.BLOCK
    ).start()
    for _ in range(5):
        await i.send("TICK")
    for _ in range(100):
        await asyncio.sleep(0.01)
        if i.context["n"] >= 5:
            break
    n = i.context["n"]
    await i.stop()
    return {"ok": n == 5, "expected": 5, "observed": n}


@attack(
    "N2-05",
    "#105: an ACTION's own self-send IS still charged (the gate did not just get disabled)",
    "the fix must narrow the gate, not remove it -- a runaway self-send must still trip",
)
async def n2_05() -> Dict[str, Any]:
    async def spin(i, ctx, e, am):  # noqa: ANN001
        await i.send("TICK")

    cfg = {
        "id": "sp",
        "initial": "up",
        "context": {"n": 0},
        "maxIterations": 20,
        "states": {"up": {"on": {"TICK": {"actions": ["spin"]}}}},
    }
    m = create_machine(cfg, logic=MachineLogic(actions={"spin": spin}))
    i = await Interpreter(m).start()
    try:
        await asyncio.wait_for(i.send("TICK", wait=True), timeout=20)
        hung = False
    except asyncio.TimeoutError:
        hung = True
    await asyncio.sleep(0.2)
    err = type(i.last_error).__name__ if i.last_error else None
    await i.stop()
    return {
        "ok": (not hung) and err == "RunawayChainError",
        "hung": hung,
        "last_error": err,
    }


@attack(
    "N2-06",
    "#105: a child actor sending to its parent is not charged to the parent's budget",
    "a supervision tree under load must not trip the parent's chain budget",
)
async def n2_06() -> Dict[str, Any]:
    child = {
        "id": "kid",
        "initial": "run",
        "states": {
            "run": {"on": {"PING": {"actions": [{"type": "sendParent", "params": {"event": "TICK"}}]}}}
        },
    }
    parent_cfg = {
        "id": "par",
        "initial": "up",
        "context": {"n": 0},
        "maxIterations": 25,
        "states": {
            "up": {
                "invoke": {"id": "kid", "src": "kid"},
                "on": {
                    "TICK": {"actions": ["inc"]},
                    "POKE": {
                        "actions": [
                            {"type": "sendTo", "params": {"to": "kid", "event": "PING"}}
                        ]
                    },
                },
            }
        },
    }
    kid = create_machine(child, logic=MachineLogic())
    def inc(i_, ctx, e, am):  # noqa: ANN001
        ctx["n"] = ctx.get("n", 0) + 1

    m = create_machine(
        parent_cfg,
        logic=MachineLogic(actions={"inc": inc}, services={"kid": kid}),
    )
    i = await Interpreter(m).start()
    N = 60
    for _ in range(N):
        await i.send("POKE")
    for _ in range(200):
        await asyncio.sleep(0.01)
        if i.context["n"] >= N:
            break
    n = i.context["n"]
    err = str(i.last_error) if i.last_error else None
    await i.stop()
    return {"ok": n == N and err is None, "expected": N, "observed": n, "last_error": err}


if __name__ == "__main__":
    main("n2_concurrency")
