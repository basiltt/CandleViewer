"""R6-13: `_get_service_executor()` (interpreter.py ~2360) hard-codes
`ThreadPoolExecutor(max_workers=4)` with no public `service_pool_size=`
argument, so more than 4 concurrent plain-`def` services serialise in
waves of 4, and because each macrostep awaits its inline service, elapsed
time is materially worse than either "run at n=4 pace" or a naive serial
run would predict once services queue behind entry into subsequent states.

Run: python R6-13_service_executor_hardcoded_pool.py
Expect (bug present): max_workers==4 on the internal executor, and wall
  time for 8 concurrent 0.2s services is roughly 2x the ideal (~0.4s vs
  ~0.2s), i.e. a step function at multiples of 4.
"""
import asyncio
import sys
import threading
import time

from xstate_statemachine import Interpreter, MachineLogic, create_machine


def make_config(n):
    return {
        "id": "pool",
        "type": "parallel",
        "states": {
            f"r{k}": {
                "initial": f"s{k}",
                "states": {
                    f"s{k}": {
                        "invoke": {
                            "src": "slow",
                            "onDone": {"target": f"d{k}"},
                        }
                    },
                    f"d{k}": {"type": "final"},
                },
            }
            for k in range(n)
        },
    }


async def main():
    live = []
    peak = {"n": 0}
    lock = threading.Lock()

    def slow(i, c, e):
        with lock:
            live.append(1)
            peak["n"] = max(peak["n"], len(live))
        time.sleep(0.2)
        with lock:
            live.pop()
        return {"ok": True}

    n = 8
    m = create_machine(make_config(n), logic=MachineLogic(services={"slow": slow}))
    i = Interpreter(m)
    t0 = time.monotonic()
    await i.start()
    # Wait for all n parallel regions to reach their own final state
    # (each region's final id starts with "d").
    final_ids = {f"pool.r{k}.d{k}" for k in range(n)}
    deadline = time.monotonic() + 5.0
    while not final_ids.issubset(i.current_state_ids) and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    elapsed = time.monotonic() - t0

    ex = i._get_service_executor()
    max_workers = getattr(ex, "_max_workers", None)

    print(f"n={n} concurrent 0.2s plain services: peak_parallel={peak['n']} elapsed={elapsed:.2f}s")
    print(f"internal executor max_workers={max_workers}")

    await i.stop()

    bug_present = max_workers == 4 and peak["n"] <= 4 and elapsed > 0.35
    if bug_present:
        print(
            "BUG CONFIRMED: the executor is hard-capped at 4 workers with "
            "no public knob, so 8 concurrent services ran in two waves "
            f"of 4 (peak_parallel={peak['n']}), roughly doubling elapsed "
            "time versus true concurrency."
        )
        sys.exit(1)
    else:
        print("Not reproduced: pool size is no longer hard-coded at 4, or concurrency was not capped.")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
