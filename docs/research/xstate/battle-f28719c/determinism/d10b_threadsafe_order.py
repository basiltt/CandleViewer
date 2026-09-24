"""D10b -- `send_threadsafe()` does not preserve the caller's arrival order
relative to `send()`.

`Interpreter.send_threadsafe` (interpreter.py:871-914) does not enqueue; it
schedules a coroutine `_deliver()` on the loop via `call_soon_threadsafe`, and
that coroutine performs the actual `send`. So the ordering point is NOT the
caller's call site -- it is whenever the loop gets round to running `_deliver`.

`Interpreter.send` from inside the loop enqueues in the same turn.

Therefore, for two producers on one interpreter, one in a thread and one in the
loop, the PROCESSED order is not the ARRIVAL order, no matter what total-order
log the application keeps. This is the minimal demonstration: a single thread
sends A, the loop then sends B, with a barrier ensuring A's call site strictly
precedes B's.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading

sys.path.insert(
    0, "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src"
)
logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    create_machine,
)

CFG = {
    "id": "ts",
    "initial": "s",
    "context": {},
    "states": {"s": {"on": {"A": {"actions": ["rec"]}, "B": {"actions": ["rec"]}}}},
}


async def run(n=20):
    order = []

    def rec(i, c, e, a):
        order.append(f"{e.type}{e.payload['k']}")

    interp = Interpreter(
        create_machine(CFG, logic=MachineLogic(actions={"rec": rec}))
    )
    await interp.start()

    sent_a = threading.Event()

    def thread_sender():
        for k in range(n):
            interp.send_threadsafe("A", k=k)
        sent_a.set()

    t = threading.Thread(target=thread_sender)
    t.start()
    # 🔒 Barrier: every `send_threadsafe("A", ...)` CALL has returned before a
    #    single `send("B", ...)` is issued. Arrival order is unambiguously
    #    A0..A(n-1) then B0..B(n-1).
    while not sent_a.is_set():
        await asyncio.sleep(0.001)
    t.join()
    for k in range(n):
        await interp.send("B", k=k)

    for _ in range(50_000):
        if len(order) >= 2 * n:
            break
        await asyncio.sleep(0)
    await interp.stop()
    return order


async def interleaved(n=20):
    """Strictly alternate: thread sends A_k, then the loop sends B_k.

    A `threading.Event` pair makes the CALL SITES strictly alternate, so the
    unambiguous arrival order is A0,B0,A1,B1,...
    """
    order = []

    def rec(i, c, e, a):
        order.append(f"{e.type}{e.payload['k']}")

    interp = Interpreter(
        create_machine(CFG, logic=MachineLogic(actions={"rec": rec}))
    )
    await interp.start()

    a_done = threading.Event()
    b_done = threading.Event()

    def thread_sender():
        for k in range(n):
            interp.send_threadsafe("A", k=k)
            a_done.set()
            while not b_done.is_set():
                pass
            b_done.clear()

    t = threading.Thread(target=thread_sender)
    t.start()
    for k in range(n):
        while not a_done.is_set():
            await asyncio.sleep(0)
        a_done.clear()
        await interp.send("B", k=k)
        b_done.set()
    t.join()

    for _ in range(100_000):
        if len(order) >= 2 * n:
            break
        await asyncio.sleep(0)
    await interp.stop()
    return order


if __name__ == "__main__":
    print("== Case 1: barrier (all A calls, then all B calls) ==")
    print("arrival: A0..A19 then B0..B19\n")
    outs = []
    for r in range(8):
        order = asyncio.run(run())
        outs.append(order)
        expected = [f"A{k}" for k in range(20)] + [f"B{k}" for k in range(20)]
        print(
            f"  run {r}: fifo={order == expected}  first 8 processed = "
            f"{order[:8]}"
        )
    expected = [f"A{k}" for k in range(20)] + [f"B{k}" for k in range(20)]
    fifo = sum(1 for o in outs if o == expected)
    distinct = len({tuple(o) for o in outs})
    print(f"\nprocessed order == arrival order: {fifo}/{len(outs)} runs")
    print(f"distinct processed orders        : {distinct}")

    print("\n== Case 2: strictly alternating call sites ==")
    exp2 = [x for k in range(20) for x in (f"A{k}", f"B{k}")]
    print(f"arrival: {exp2[:8]} ...\n")
    outs2 = []
    for r in range(8):
        o = asyncio.run(interleaved())
        outs2.append(o)
        print(f"  run {r}: fifo={o == exp2}  first 8 processed = {o[:8]}")
    fifo2 = sum(1 for o in outs2 if o == exp2)
    distinct2 = len({tuple(o) for o in outs2})
    print(f"\nprocessed order == arrival order: {fifo2}/{len(outs2)} runs")
    print(f"distinct processed orders        : {distinct2}")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "d10b_threadsafe.json"), "w", encoding="utf-8") as f:
        json.dump(
            {
                "case1_barrier": {
                    "fifo_runs": fifo,
                    "runs": len(outs),
                    "distinct": distinct,
                },
                "case2_alternating": {
                    "fifo_runs": fifo2,
                    "runs": len(outs2),
                    "distinct": distinct2,
                    "expected_head": exp2[:10],
                    "observed_heads": [o[:10] for o in outs2],
                },
            },
            f,
            indent=2,
        )
