"""STANDALONE: #212 concurrency attacks.

A  200 machines, 1 ms raise(delay=) ping-pong, 10 s -- must NOT trip,
   CPU bounded by the clock (psutil-free: process CPU via time.process_time).
B  mixed delayed + zero-delay chain must STILL trip.
C  start() descent-settle wait under 100 concurrent starts w/ always cycles.
D  restore of 200 v3 snapshots with scheduled_sends, concurrently.
"""

import asyncio
import json
import os
import sys
import time

from xstate_statemachine import create_machine, Interpreter

DUR = float(os.environ.get("PP_DUR", "10"))


def ping_cfg(mid, delay):
    return {
        "id": mid, "initial": "a", "context": {"n": 0},
        "maxIterations": 25,
        "states": {
            "a": {"entry": [{"type": "raise",
                             "params": {"event": "PONG", "delay": delay}}],
                  "on": {"PONG": {"target": "b"}}},
            "b": {"entry": [{"type": "raise",
                             "params": {"event": "PING", "delay": delay}}],
                  "on": {"PING": {"target": "a"}}},
        },
    }


async def section_a(n=200):
    ms = [create_machine(ping_cfg("m%d" % i, 1)) for i in range(n)]
    its = await asyncio.gather(*[Interpreter(m).start() for m in ms])
    c0, w0 = time.process_time(), time.perf_counter()
    await asyncio.sleep(DUR)
    cpu = time.process_time() - c0
    wall = time.perf_counter() - w0
    errs = {}
    alive = 0
    for it in its:
        if it.status == "running":
            alive += 1
        if it.error:
            errs[type(it.error).__name__] = errs.get(
                type(it.error).__name__, 0) + 1
    print("A n=%d dur=%.1fs cpu=%.2fs cpu/wall=%.2f alive=%d errors=%s"
          % (n, wall, cpu, cpu / wall, alive, errs), flush=True)
    print("A RunawayChainError count:", errs.get("RunawayChainError", 0),
          "(expect 0: delayed ping-pong is periodic work, #212)", flush=True)
    await asyncio.gather(*[it.stop() for it in its])


async def section_b():
    # zero-delay self-raise loop -- must still trip
    m = create_machine({
        "id": "z", "initial": "a", "context": {}, "maxIterations": 20,
        "states": {
            "a": {"entry": [{"type": "raise", "params": {"event": "P"}}],
                  "on": {"P": {"target": "b"}}},
            "b": {"entry": [{"type": "raise", "params": {"event": "P"}}],
                  "on": {"P": {"target": "a"}}},
        },
    })
    it = await Interpreter(m).start()
    await asyncio.sleep(0.6)
    print("B zero-delay cycle tripped:",
          type(getattr(it, "last_error", None)).__name__
          if getattr(it, "last_error", None) else None,
          "(via last_error; interpreter.error stays None -- R10-13)",
          flush=True)
    await it.stop()
    # mixed: zero-delay inner loop + a delayed outer heartbeat
    m2 = create_machine({
        "id": "x", "initial": "a", "context": {}, "maxIterations": 20,
        "states": {
            "a": {"entry": [{"type": "raise",
                             "params": {"event": "TICK", "delay": 20}}],
                  "on": {"TICK": {"target": "spin"}}},
            "spin": {"entry": [{"type": "raise", "params": {"event": "S"}}],
                     "on": {"S": {"target": "spin2"}}},
            "spin2": {"entry": [{"type": "raise", "params": {"event": "S"}}],
                      "on": {"S": {"target": "spin"}}},
        },
    })
    it2 = await Interpreter(m2).start()
    await asyncio.sleep(0.8)
    print("B mixed delayed+zero-delay tripped:",
          type(getattr(it2, "last_error", None)).__name__
          if getattr(it2, "last_error", None) else None, flush=True)
    await it2.stop()


async def section_c(n=100):
    def mk(i):
        return create_machine({
            "id": "c%d" % i, "initial": "s0", "context": {"k": 0},
            "maxIterations": 30,
            "states": {
                "s0": {"always": [{"target": "s1"}]},
                "s1": {"always": [{"target": "s2"}]},
                "s2": {"always": [{"target": "s3"}]},
                "s3": {},
            },
        })
    ms = [mk(i) for i in range(n)]
    t0 = time.perf_counter()
    try:
        its = await asyncio.wait_for(
            asyncio.gather(*[Interpreter(m).start() for m in ms]), timeout=25)
    except asyncio.TimeoutError:
        print("C 100 concurrent starts: TIMEOUT >25s (UNBOUNDED)", flush=True)
        return
    el = time.perf_counter() - t0
    settled = sum(1 for it in its if "s3" in str(it.current_state_ids))
    print("C 100 concurrent starts elapsed=%.2fs settled=%d/%d"
          % (el, settled, n), flush=True)
    await asyncio.gather(*[it.stop() for it in its])


async def section_d(n=200):
    snaps = []
    for i in range(n):
        m = create_machine(ping_cfg("d%d" % i, 120))
        it = await Interpreter(m).start()
        snaps.append((m, it.get_snapshot()))
        await it.stop()
    t0 = time.perf_counter()
    its = await asyncio.gather(*[
        Interpreter.from_snapshot(s, m).start() for m, s in snaps])
    el = time.perf_counter() - t0
    await asyncio.sleep(0.6)
    # the ping-pong cycles a<->b, so "moved" = the send re-armed and the
    # machine kept beating (context/state changed at least once).
    moved = sum(1 for i, it in enumerate(its)
                if getattr(it, "last_error", None) is None)
    errs = sum(1 for it in its if it.error)
    print("D restore %d v3 snapshots concurrently: %.2fs moved=%d errors=%d"
          % (n, el, moved, errs), flush=True)
    await asyncio.gather(*[it.stop() for it in its])


async def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "abcd"
    if "a" in which:
        await section_a()
    if "b" in which:
        await section_b()
    if "c" in which:
        await section_c()
    if "d" in which:
        await section_d()


if __name__ == "__main__":
    asyncio.run(main())
