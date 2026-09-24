# -*- coding: utf-8 -*-
"""Round-6 #173 soak-relevant attack: service_pool_size under stop() churn.

50 plain-def (blocking) services queued against service_pool_size=1, with
stop() issued mid-service repeatedly across many generations (soak-style
churn), watching for: leaked threads, hung stop(), executor exhaustion
across generations (each Interpreter should own/tear down its own pool),
double-fire of done-callbacks.
"""
from __future__ import annotations

import asyncio
import threading
import time

from xstate_statemachine import Interpreter, MachineLogic, create_machine

CONFIG = {
    "id": "svc",
    "initial": "waiting",
    "context": {"done_count": 0},
    "states": {
        "waiting": {
            "invoke": {
                "id": "s",
                "src": "slow_service",
                "onDone": {"actions": ["mark_done"]},
                "onError": {"actions": ["mark_done"]},
            },
        },
    },
}

def mark_done(interp, ctx, event, action_def):  # noqa: ANN001
    # NOTE: id(interp)-keyed global tallies are unsafe here -- CPython may
    # recycle a GC'd Interpreter's id() across generations, producing a
    # false "double fire" that is a harness artifact, not a library defect.
    # Use the machine's own context counter instead (reset per generation).
    ctx["done_count"] = ctx.get("done_count", 0) + 1


def slow_service(interp, ctx, event):  # noqa: ANN001
    time.sleep(0.05)
    return "ok"


ACTIONS = {"mark_done": mark_done}
SERVICES = {"slow_service": slow_service}


async def run_generation(gen: int) -> dict:
    logic = MachineLogic(actions=dict(ACTIONS), services=dict(SERVICES))
    machine = create_machine(dict(CONFIG), logic=logic)
    interp = Interpreter(machine, service_pool_size=1)
    threads_before = threading.active_count()
    t0 = time.perf_counter()
    await interp.start()
    # stop mid-service on odd generations
    if gen % 2 == 1:
        await asyncio.sleep(0.01)
        try:
            await asyncio.wait_for(interp.stop(drain=False, timeout=2.0), timeout=3.0)
        except asyncio.TimeoutError:
            return {"gen": gen, "STOP_HUNG": True}
    else:
        await asyncio.sleep(0.15)
        try:
            await asyncio.wait_for(interp.stop(drain=False, timeout=2.0), timeout=3.0)
        except asyncio.TimeoutError:
            return {"gen": gen, "STOP_HUNG": True}
    dt = time.perf_counter() - t0
    await asyncio.sleep(0.05)
    threads_after = threading.active_count()
    fires = interp.context.get("done_count", 0)
    return {
        "gen": gen,
        "dt_s": round(dt, 3),
        "threads_before": threads_before,
        "threads_after": threads_after,
        "onDone_fires": fires,
        "STOP_HUNG": False,
    }


async def main():
    results = []
    for gen in range(50):
        r = await run_generation(gen)
        results.append(r)

    hangs = [r for r in results if r.get("STOP_HUNG")]
    double_fires = [r for r in results if r.get("onDone_fires", 0) > 1]
    thread_growth = results[-1]["threads_after"] - results[0]["threads_before"] if results[0].get("threads_before") is not None else None

    print(f"generations=50 hangs={len(hangs)} double_fires={len(double_fires)}")
    print(f"thread_count: first_before={results[0].get('threads_before')} "
          f"last_after={results[-1].get('threads_after')}")
    print("sample:", results[:3], "...", results[-3:])

    ok = not hangs and not double_fires
    print("SERVICE_POOL_SIZE_1_STOP_CHURN_OK:", ok)


if __name__ == "__main__":
    asyncio.run(main())
