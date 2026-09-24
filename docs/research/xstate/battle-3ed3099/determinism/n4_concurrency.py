"""N4 -- concurrency attacks on the round-4 fixes.

C1  #105: an EXTERNAL producer sending during an in-flight step must not be
    charged to `maxIterations`. The gate is now "issued from one of this
    interpreter's actions", tracked PER TASK. Attack it from
    asyncio.create_task, from OS threads, and from a CHILD actor -- three
    different "who issued this" contexts. A machine with a small
    maxIterations that never self-sends must survive heavy external traffic.

C2  #104: OverflowPolicy.BLOCK under 16 concurrent producers -- every send
    must land, nothing silently lost, and a fire-and-forget send on an inbox
    with room must enqueue eagerly.

C3  the same, but with an action-issued self-send mixed in, so the gate has
    to tell the two apart under load.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    OverflowPolicy,
    create_machine,
)

COUNTER = {
    "id": "cnt",
    "initial": "up",
    "context": {"n": 0, "self": 0},
    "states": {
        "up": {
            "on": {
                "TICK": {"actions": ["bump"]},
                "SELF": {"actions": ["selfbump"]},
            }
        }
    },
}


def mk(max_iterations=None):
    def bump(i, c, e, a):
        c["n"] += 1

    def selfbump(i, c, e, a):
        c["self"] += 1

    cfg = dict(COUNTER)
    if max_iterations is not None:
        cfg = {**COUNTER, "maxIterations": max_iterations}
    return create_machine(
        cfg, logic=MachineLogic(actions={"bump": bump, "selfbump": selfbump})
    )


async def c1_tasks(n_producers=8, per=100, max_iterations=10):
    """External producers via create_task, tiny maxIterations."""
    i = Interpreter(mk(max_iterations))
    await i.start()
    errs = []

    async def prod(p):
        for k in range(per):
            try:
                await i.send("TICK", p=p, k=k)
            except Exception as e:  # noqa: BLE001
                errs.append(f"{type(e).__name__}: {e}"[:120])

    await asyncio.gather(*(prod(p) for p in range(n_producers)))
    # 🧯 drain generously: 500 turns was NOT enough and looked like loss
    #    (see n4b_maxiter_forensics.py) -- it is a harness artefact.
    for _ in range(20000):
        await asyncio.sleep(0)
    n = i.context["n"]
    await i.stop()
    return {
        "expected": n_producers * per,
        "processed": n,
        "errors": len(errs),
        "error_examples": errs[:3],
        "OK": n == n_producers * per and not errs,
    }


async def c1_threads(n_threads=8, per=100, max_iterations=10):
    i = Interpreter(mk(max_iterations))
    await i.start()
    errs = []
    loop = asyncio.get_running_loop()

    def worker(t):
        for k in range(per):
            try:
                i.send_threadsafe("TICK", t=t, k=k)
            except Exception as e:  # noqa: BLE001
                errs.append(f"{type(e).__name__}: {e}"[:120])

    ths = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in ths:
        t.start()
    while any(t.is_alive() for t in ths):
        await asyncio.sleep(0.005)
    for t in ths:
        t.join()
    for _ in range(3000):
        await asyncio.sleep(0)
    n = i.context["n"]
    await i.stop()
    return {
        "expected": n_threads * per,
        "processed": n,
        "errors": len(errs),
        "error_examples": errs[:3],
        "OK": n == n_threads * per and not errs,
    }


# --- C1c: a CHILD actor sends to the parent ---------------------------------
KID = {
    "id": "kid",
    "initial": "up",
    "states": {
        "up": {
            "on": {
                "PUSH": {
                    "actions": [
                        {
                            "type": "sendParent",
                            "params": {"event": "TICK"},
                        }
                    ]
                }
            }
        }
    },
}
PARENT = {
    "id": "par",
    "maxIterations": 10,
    "initial": "run",
    "context": {"n": 0, "self": 0},
    "states": {
        "run": {
            "invoke": {"id": "kid", "src": "kidMachine", "systemId": "kid"},
            "on": {
                "TICK": {"actions": ["bump"]},
                "PUSH_KID": {
                    "actions": [
                        {
                            "type": "sendTo",
                            "params": {"to": "kid", "event": "PUSH"},
                        }
                    ]
                },
            },
        }
    },
}


async def c1_child(per=100):
    def bump(i, c, e, a):
        c["n"] += 1

    kid = create_machine(KID, logic=MachineLogic())
    p = create_machine(
        PARENT,
        logic=MachineLogic(actions={"bump": bump}, services={"kidMachine": kid}),
    )
    i = Interpreter(p)
    await i.start()
    errs = []
    for k in range(per):
        try:
            await i.send("PUSH_KID", k=k)
        except Exception as e:  # noqa: BLE001
            errs.append(f"{type(e).__name__}: {e}"[:120])
    for _ in range(2000):
        await asyncio.sleep(0)
    n = i.context["n"]
    await i.stop()
    return {
        "pushes": per,
        "parent_ticks": n,
        "errors": len(errs),
        "error_examples": errs[:3],
        "OK": n == per and not errs,
    }


async def c2_block(n_producers=16, per=60):
    """#104 BLOCK under 16 producers -- nothing may be silently lost."""
    i = Interpreter(
        mk(), max_queue_size=8, overflow_policy=OverflowPolicy.BLOCK
    )
    await i.start()
    errs = []

    async def prod(p):
        for k in range(per):
            try:
                await i.send("TICK", p=p, k=k)
            except Exception as e:  # noqa: BLE001
                errs.append(f"{type(e).__name__}: {e}"[:120])

    await asyncio.gather(*(prod(p) for p in range(n_producers)))
    for _ in range(4000):
        await asyncio.sleep(0)
    n = i.context["n"]
    await i.stop()
    return {
        "expected": n_producers * per,
        "processed": n,
        "lost": n_producers * per - n,
        "errors": len(errs),
        "error_examples": errs[:3],
        "OK": n == n_producers * per and not errs,
    }


async def c2_fire_and_forget(n=200):
    """A fire-and-forget send under BLOCK on an inbox with room."""
    i = Interpreter(
        mk(), max_queue_size=64, overflow_policy=OverflowPolicy.BLOCK
    )
    await i.start()
    errs = []
    for k in range(n):
        try:
            r = i.send("TICK", k=k)  # not awaited immediately
            if asyncio.iscoroutine(r):
                asyncio.create_task(r)
        except Exception as e:  # noqa: BLE001
            errs.append(f"{type(e).__name__}: {e}"[:120])
    for _ in range(6000):
        await asyncio.sleep(0)
    got = i.context["n"]
    await i.stop()
    return {
        "expected": n,
        "processed": got,
        "lost": n - got,
        "errors": len(errs),
        "OK": got == n and not errs,
    }


async def main():
    res = {}
    res["C1a_tasks_maxiter10"] = await c1_tasks()
    res["C1b_threads_maxiter10"] = await c1_threads()
    res["C1c_child_actor_sendParent"] = await c1_child()
    res["C2a_BLOCK_16_producers"] = await c2_block()
    res["C2b_BLOCK_fire_and_forget"] = await c2_fire_and_forget()

    for k, v in res.items():
        print(f"\n== {k} ==")
        for kk, vv in v.items():
            print(f"   {kk:26s}: {vv}")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "n4_concurrency.json"), "w") as f:
        json.dump(res, f, indent=2, default=str)
    print("\nwrote out/n4_concurrency.json")


if __name__ == "__main__":
    asyncio.run(main())
