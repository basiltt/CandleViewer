# -*- coding: utf-8 -*-
"""Verify #173 on main @ 221ce7c: `Interpreter(service_pool_size=N)` is a
public knob controlling the internally-created plain-service executor's
worker count (was hard-coded `ThreadPoolExecutor(max_workers=4)`), and
`DEFAULT_SERVICE_POOL_SIZE` documents the default.

Criteria:
 1. `DEFAULT_SERVICE_POOL_SIZE` is importable and equals 4 (unchanged
    default, now named/public).
 2. With no `service_pool_size` given, 8 concurrent 0.2s plain services
    across 8 parallel regions still peak at 4 concurrent (old default
    behaviour preserved) and take > 0.35s (two waves).
 3. With `service_pool_size=8`, the same machine's internal executor
    reports `max_workers == 8`, peak concurrency reaches 8, and elapsed
    time is close to a single 0.2s wave (< 0.35s) -- i.e. materially
    faster than the pool=4 case.
 4. The public docstring on `Interpreter.__init__` documents the
    (N+1)-th-service-waits / macrostep-blocking interaction (spot-checked
    via the docstring text itself).

Exit 0 if all criteria pass, 1 otherwise.
"""
import asyncio
import sys
import threading
import time

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.interpreter import DEFAULT_SERVICE_POOL_SIZE

N = 8


def make_config(n):
    return {
        "id": "pool",
        "type": "parallel",
        "states": {
            f"r{k}": {
                "initial": f"s{k}",
                "states": {
                    f"s{k}": {"invoke": {"src": "slow", "onDone": {"target": f"d{k}"}}},
                    f"d{k}": {"type": "final"},
                },
            }
            for k in range(n)
        },
    }


def make_slow(peak):
    live = []
    lock = threading.Lock()

    def slow(i, c, e):
        with lock:
            live.append(1)
            peak["n"] = max(peak["n"], len(live))
        time.sleep(0.2)
        with lock:
            live.pop()
        return {"ok": True}

    return slow


async def run(pool_size_kwargs):
    peak = {"n": 0}
    m = create_machine(make_config(N), logic=MachineLogic(services={"slow": make_slow(peak)}))
    i = Interpreter(m, **pool_size_kwargs)
    t0 = time.monotonic()
    await i.start()
    final_ids = {f"pool.r{k}.d{k}" for k in range(N)}
    deadline = time.monotonic() + 5.0
    while not final_ids.issubset(i.current_state_ids) and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    elapsed = time.monotonic() - t0
    ex = i._get_service_executor()
    max_workers = getattr(ex, "_max_workers", None)
    await i.stop()
    return peak["n"], elapsed, max_workers


def main():
    c1 = DEFAULT_SERVICE_POOL_SIZE == 4
    print(f"[1] DEFAULT_SERVICE_POOL_SIZE == 4: {c1} (={DEFAULT_SERVICE_POOL_SIZE})")

    peak_default, elapsed_default, mw_default = asyncio.run(run({}))
    print(f"default pool: peak={peak_default} elapsed={elapsed_default:.2f}s max_workers={mw_default}")
    c2 = mw_default == 4 and peak_default <= 4 and elapsed_default > 0.35
    print(f"[2] default behaviour unchanged (capped at 4, two waves): {c2}")

    peak_wide, elapsed_wide, mw_wide = asyncio.run(run({"service_pool_size": N}))
    print(f"pool={N}   : peak={peak_wide} elapsed={elapsed_wide:.2f}s max_workers={mw_wide}")
    c3 = mw_wide == N and peak_wide == N and elapsed_wide < 0.35 and elapsed_wide < elapsed_default * 0.7
    print(f"[3] service_pool_size={N} widens concurrency and is faster: {c3}")

    doc = Interpreter.__init__.__doc__ or ""
    c4 = "service_pool_size" in doc and ("waits for a" in doc or "macrostep" in doc)
    print(f"[4] docstring documents the knob + macrostep-blocking interaction: {c4}")

    ok = c1 and c2 and c3 and c4
    print("RESULT:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
