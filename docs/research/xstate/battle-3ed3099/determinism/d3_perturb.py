"""D3 -- scheduling perturbation: does *only* changing asyncio interleaving
change the machine's observable behaviour?

Two perturbations, event script held fixed:

  P1 (jitter): every invoked service awaits a random number of `sleep(0)`
      turns before returning. The machine's logic is unchanged; only the
      number of loop turns between an invoke and its completion changes.
      Question: does the transition trace / action order / context change?

  P2 (concurrent senders): 8 asyncio tasks each send a disjoint slice of one
      total event order. Each task records the exact instant (a monotonically
      increasing global counter taken immediately before `await interp.send`)
      so we have a ground-truth ARRIVAL order. Question: is the PROCESSED
      order equal to arrival order, and is it stable across runs?

Run: python d3_perturb.py
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import os
import random
import sys

sys.path.insert(
    0, "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src"
)
logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    create_machine,
)
from xstate_statemachine.clock import SimulatedClock  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

# -----------------------------------------------------------------------------
# P1 -- service jitter
# -----------------------------------------------------------------------------
P1_CFG = {
    "id": "p1",
    "initial": "idle",
    "context": {"ok": 0, "n": 0},
    "states": {
        "idle": {"on": {"GO": {"target": "busy"}, "TICK": {"actions": ["n"]}}},
        "busy": {
            "invoke": {
                "id": "svc",
                "src": "work",
                "onDone": {"target": "idle", "actions": ["ok"]},
            },
            "on": {"TICK": {"actions": ["n"]}, "ABORT": {"target": "idle"}},
        },
    },
}


async def p1_run(script, jitter_seed):
    trace = []
    rng = random.Random(jitter_seed)

    def n(i, c, e, a):
        trace.append(("n", e.type))
        c["n"] += 1

    def ok(i, c, e, a):
        trace.append(("ok", e.type))
        c["ok"] += 1

    async def work(i, c, e):
        # ⏱️ pure scheduling perturbation: no logic depends on this
        for _ in range(rng.randrange(0, 8)):
            await asyncio.sleep(0)
        return {"v": c["n"]}

    m = create_machine(
        P1_CFG,
        logic=MachineLogic(
            actions={"n": n, "ok": ok}, services={"work": work}
        ),
    )
    interp = Interpreter(m, clock=SimulatedClock())
    await interp.start()
    for t in script:
        await interp.send(t)
    # let every in-flight service land
    for _ in range(200):
        await asyncio.sleep(0)
    out = (trace, dict(interp.context), sorted(interp.current_state_ids))
    await interp.stop()
    return out


def p1(runs=25):
    rng = random.Random(7)
    script = [
        rng.choice(["GO", "TICK", "TICK", "ABORT", "TICK"]) for _ in range(400)
    ]
    results = [asyncio.run(p1_run(script, s)) for s in range(runs)]
    base = results[0]
    same_trace = sum(1 for r in results if r[0] == base[0])
    same_ctx = sum(1 for r in results if r[1] == base[1])
    same_state = sum(1 for r in results if r[2] == base[2])
    print("=== P1: service jitter (identical event script, %d runs) ===" % runs)
    print(f"  identical action trace : {same_trace}/{runs}")
    print(f"  identical final context: {same_ctx}/{runs}")
    print(f"  identical final state  : {same_state}/{runs}")
    ctxs = {json.dumps(r[1], sort_keys=True) for r in results}
    print(f"  distinct final contexts: {len(ctxs)} -> {sorted(ctxs)[:4]}")
    if same_trace != runs:
        for r in results:
            if r[0] != base[0]:
                for i, (a, b) in enumerate(zip(base[0], r[0])):
                    if a != b:
                        print(f"  first trace diff @ {i}: {a!r} vs {b!r}")
                        break
                else:
                    print(
                        f"  trace lengths differ: {len(base[0])} vs {len(r[0])}"
                    )
                break
    return {
        "same_trace": same_trace,
        "same_ctx": same_ctx,
        "same_state": same_state,
        "runs": runs,
        "distinct_contexts": len(ctxs),
    }


# -----------------------------------------------------------------------------
# P2 -- 8 concurrent senders with a ground-truth total order
# -----------------------------------------------------------------------------
P2_CFG = {
    "id": "p2",
    "initial": "a",
    "context": {"seq": []},
    "states": {"a": {"on": {"E": {"actions": ["rec"]}}}},
}


async def p2_run(n_tasks=8, per_task=250, jitter=True):
    processed = []
    counter = itertools.count()
    arrival = []

    def rec(i, c, e, a):
        processed.append(e.payload["k"])

    m = create_machine(P2_CFG, logic=MachineLogic(actions={"rec": rec}))
    interp = Interpreter(m, clock=SimulatedClock())
    await interp.start()

    lock = asyncio.Lock()

    async def sender(tid):
        for j in range(per_task):
            if jitter and (j % 3 == 0):
                await asyncio.sleep(0)
            # 📌 ground truth: stamp under a lock IMMEDIATELY before the
            #    send, and do not await between the stamp and the enqueue.
            async with lock:
                k = next(counter)
                arrival.append(k)
                await interp.send("E", k=k, tid=tid)

    await asyncio.gather(*[sender(t) for t in range(n_tasks)])
    # 🚰 drain properly: wait until the inbox is empty AND nothing new lands
    #    for several consecutive turns, bounded so a hang is visible.
    total = n_tasks * per_task
    idle = 0
    for _ in range(200_000):
        if len(processed) >= total:
            break
        before = len(processed)
        await asyncio.sleep(0)
        idle = idle + 1 if len(processed) == before else 0
        if idle > 2000 and interp.queue_depth == 0:
            break
    out = (list(arrival), list(processed), interp.queue_depth)
    await interp.stop()
    return out


def p2(runs=20):
    print("\n=== P2: 8 concurrent senders vs arrival order (%d runs) ===" % runs)
    rows = []
    for r in range(runs):
        arrival, processed, depth = asyncio.run(p2_run())
        lost = len(arrival) - len(processed)
        fifo = processed == arrival
        first_inv = None
        for i, (a, b) in enumerate(zip(arrival, processed)):
            if a != b:
                first_inv = (i, a, b)
                break
        rows.append(
            {
                "run": r,
                "sent": len(arrival),
                "processed": len(processed),
                "lost": lost,
                "queue_depth_at_end": depth,
                "fifo": fifo,
                "first_inversion": first_inv,
            }
        )
    n_fifo = sum(1 for x in rows if x["fifo"])
    n_lost = sum(1 for x in rows if x["lost"])
    print(f"  processed order == arrival order : {n_fifo}/{runs} runs")
    print(f"  runs with lost events            : {n_lost}/{runs}")
    print(f"  events per run                   : {rows[0]['sent']}")
    print(f"  queue depth at end               : {sorted({x['queue_depth_at_end'] for x in rows})}")
    if n_fifo < runs:
        for x in rows:
            if not x["fifo"]:
                print(
                    f"  example inversion (run {x['run']}): "
                    f"index/arrival/processed = {x['first_inversion']}, "
                    f"lost={x['lost']}"
                )
                break
    if n_lost:
        print(
            "  lost counts: "
            + str(sorted({x["lost"] for x in rows if x["lost"]}))
        )
    seqs = set()
    for r in range(5):
        _, p, _ = asyncio.run(p2_run())
        seqs.add(tuple(p))
    print(f"  distinct processed orders over 5 further runs: {len(seqs)}")
    return {"fifo_runs": n_fifo, "runs": runs, "lost_runs": n_lost, "rows": rows[:5]}


if __name__ == "__main__":
    res = {"p1": p1(), "p2": p2()}
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "d3_perturb.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)
    print("\nwrote out/d3_perturb.json")
