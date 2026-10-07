"""D10 -- concurrent producers, total-order log, and `send_threadsafe`.

Three scenarios, each with a ground-truth arrival order recorded under a lock
immediately before the enqueue call:

  T1  8 asyncio tasks -> `await interp.send(...)`.
      (D3/P2 already covers this; repeated here at higher contention and with
      random `sleep(0)` jitter inside each sender.)

  T2  8 OS THREADS -> `interp.send_threadsafe(...)`, which is the only
      supported cross-thread entry point (#37/#78).

  T3  Mixed: 4 asyncio tasks + 4 OS threads against ONE interpreter.

For each: is processed order == arrival order, is it stable across runs, and
is anything lost?
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import os
import random
import sys
import threading

sys.path.insert(
    0, "<workspace>/_ref/xstate-statemachine/src"
)
logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    create_machine,
)

CFG = {
    "id": "t",
    "initial": "s",
    "context": {},
    "states": {"s": {"on": {"E": {"actions": ["rec"]}}}},
}


def mk(order):
    def rec(i, c, e, a):
        order.append(e.payload["k"])

    return create_machine(CFG, logic=MachineLogic(actions={"rec": rec}))


async def drain(interp, processed, total):
    idle = 0
    for _ in range(500_000):
        if len(processed) >= total:
            return True
        before = len(processed)
        await asyncio.sleep(0)
        idle = idle + 1 if len(processed) == before else 0
        if idle > 5000 and interp.queue_depth == 0:
            return False
    return False


# -----------------------------------------------------------------------------
async def t1(tasks=8, per=300, seed=0):
    order, arrival = [], []
    counter = itertools.count()
    rng = random.Random(seed)
    interp = Interpreter(mk(order))
    await interp.start()
    lock = asyncio.Lock()

    async def sender(tid):
        for _ in range(per):
            if rng.randrange(4) == 0:
                await asyncio.sleep(0)
            async with lock:
                k = next(counter)
                arrival.append(k)
                await interp.send("E", k=k)

    await asyncio.gather(*[sender(t) for t in range(tasks)])
    complete = await drain(interp, order, tasks * per)
    out = (list(arrival), list(order), complete)
    await interp.stop()
    return out


# -----------------------------------------------------------------------------
async def t2(threads=8, per=300):
    order, arrival = [], []
    counter = itertools.count()
    interp = Interpreter(mk(order))
    await interp.start()
    lock = threading.Lock()
    done = threading.Event()

    def sender(tid):
        for _ in range(per):
            with lock:
                k = next(counter)
                arrival.append(k)
                interp.send_threadsafe("E", k=k)

    ths = [threading.Thread(target=sender, args=(t,)) for t in range(threads)]

    async def spin():
        for t in ths:
            t.start()
        while any(t.is_alive() for t in ths):
            await asyncio.sleep(0)
        for t in ths:
            t.join()

    await spin()
    complete = await drain(interp, order, threads * per)
    out = (list(arrival), list(order), complete)
    await interp.stop()
    return out


# -----------------------------------------------------------------------------
async def t3(n=4, per=250):
    order, arrival = [], []
    counter = itertools.count()
    interp = Interpreter(mk(order))
    await interp.start()
    lock = threading.Lock()

    def tsender(tid):
        for _ in range(per):
            with lock:
                k = next(counter)
                arrival.append(k)
                interp.send_threadsafe("E", k=k)

    async def asender(tid):
        for _ in range(per):
            with lock:
                k = next(counter)
                arrival.append(k)
            await interp.send("E", k=k)
            await asyncio.sleep(0)

    ths = [threading.Thread(target=tsender, args=(t,)) for t in range(n)]
    for t in ths:
        t.start()
    await asyncio.gather(*[asender(i) for i in range(n)])
    while any(t.is_alive() for t in ths):
        await asyncio.sleep(0)
    for t in ths:
        t.join()
    complete = await drain(interp, order, 2 * n * per)
    out = (list(arrival), list(order), complete)
    await interp.stop()
    return out


def report(name, fn, runs=10, **kw):
    print(f"\n=== {name} ===")
    rows = []
    for r in range(runs):
        arrival, processed, complete = asyncio.run(fn(**kw))
        first_inv = None
        for i, (a, b) in enumerate(zip(arrival, processed)):
            if a != b:
                first_inv = (i, a, b)
                break
        rows.append(
            {
                "sent": len(arrival),
                "processed": len(processed),
                "lost": len(arrival) - len(processed),
                "fifo": processed == arrival,
                "first_inversion": first_inv,
                "drained": complete,
            }
        )
    fifo = sum(1 for x in rows if x["fifo"])
    lost = sum(1 for x in rows if x["lost"])
    print(f"  sent per run              : {rows[0]['sent']}")
    print(f"  processed == arrival order: {fifo}/{runs} runs")
    print(f"  runs with lost events     : {lost}/{runs}")
    print(f"  runs that fully drained   : {sum(1 for x in rows if x['drained'])}/{runs}")
    if fifo < runs:
        for x in rows:
            if not x["fifo"]:
                print(
                    f"  example: first inversion at processed-index "
                    f"{x['first_inversion'][0]}: arrival "
                    f"{x['first_inversion'][1]} vs processed "
                    f"{x['first_inversion'][2]}; lost={x['lost']}"
                )
                break
    if lost:
        print(f"  lost counts: {sorted({x['lost'] for x in rows if x['lost']})}")
    return {"name": name, "fifo_runs": fifo, "runs": runs, "rows": rows}


if __name__ == "__main__":
    res = [
        report("T1  8 asyncio tasks -> send()", t1),
        report("T2  8 OS threads -> send_threadsafe()", t2),
        report("T3  4 tasks + 4 threads, one interpreter", t3),
    ]
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "d10_concurrent.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2, default=str)
    print("\nwrote out/d10_concurrent.json")
