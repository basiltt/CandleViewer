"""STANDALONE: livelock fuzzer with delayed raises in the grammar (#212).

Oracle (post-#212):
  * a cycle whose every arm is a ZERO-delay raise/always  -> MUST trip
    (RunawayChainError observable via last_error).
  * a cycle containing at least one arm with delay >= 1ms -> MUST NOT
    trip, and MUST beat at least N times (legal periodic work).
Both engines, both service kinds are irrelevant here (no services); the
kind axis is covered by the entry-action style (def vs async def).
"""

import asyncio
import random
import sys
import time

from xstate_statemachine import create_machine, Interpreter, MachineLogic
from xstate_statemachine.sync_interpreter import SyncInterpreter

MI = 12
BEATS_MIN = 3


def make(rng, i, kind):
    n = rng.randint(2, 4)
    delays = [rng.choice([0, 0, 0, 1, 2, 5]) for _ in range(n)]
    if rng.random() < 0.4:
        delays = [0] * n          # guaranteed zero-delay cycle
    states = {}
    for k in range(n):
        nxt = "s%d" % ((k + 1) % n)
        ev = "E%d" % k
        d = delays[k]
        params = {"event": ev}
        if d:
            params["delay"] = d
        states["s%d" % k] = {
            "entry": [{"type": "inc"},
                      {"type": "raise", "params": params}],
            "on": {ev: {"target": nxt}},
        }
    cfg = {"id": "f%d" % i, "initial": "s0", "context": {"n": 0},
           "maxIterations": MI, "states": states}
    return cfg, any(d >= 1 for d in delays)


def inc_def(i, c, e, a):
    c["n"] = c.get("n", 0) + 1


async def inc_async(i, c, e, a):
    c["n"] = c.get("n", 0) + 1


async def run_async(cfg, kind, dwell):
    logic = MachineLogic(
        actions={"inc": inc_def if kind == "def" else inc_async})
    m = create_machine(cfg, logic=logic)
    it = await Interpreter(m).start()
    await asyncio.sleep(dwell)
    tripped = type(getattr(it, "last_error", None)).__name__ \
        == "RunawayChainError"
    beats = it.context["n"]
    await it.stop()
    return tripped, beats


def run_sync(cfg, dwell):
    m = create_machine(cfg, logic=MachineLogic(actions={"inc": inc_def}))
    it = SyncInterpreter(m).start()
    # 🧷 the zero-delay trip happens during start()'s descent; a LATER
    #    successful send() clears `last_error`, so latch it before pumping
    #    and on every pump (see n8_last_error_clearing.py).
    def tripped_now():
        return type(getattr(it, "last_error", None)).__name__ == (
            "RunawayChainError")

    tripped = tripped_now()
    # sync engine needs an external pump for clock events
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < dwell:
        it.send("__NUDGE__")
        time.sleep(0.002)
        tripped = tripped or tripped_now()
    beats = it.context["n"]
    it.stop()
    return tripped, beats


async def main(n):
    rng = random.Random(7)
    res = {}
    bad = []
    for i in range(n):
        cfg, periodic = make(rng, i, None)
        dwell = 0.08 if not periodic else 0.15
        for kind in ("def", "async"):
            tripped, beats = await run_async(dict(cfg), kind, dwell)
            label = ("periodic" if periodic else "zero") + "/async/" + kind
            ok = (not tripped and beats >= BEATS_MIN) if periodic else tripped
            res[label + ("/OK" if ok else "/VIOLATION")] = \
                res.get(label + ("/OK" if ok else "/VIOLATION"), 0) + 1
            if not ok and len(bad) < 10:
                bad.append((label, cfg["id"], tripped, beats))
        tripped, beats = run_sync(dict(cfg), dwell)
        label = ("periodic" if periodic else "zero") + "/sync/def"
        ok = (not tripped and beats >= BEATS_MIN) if periodic else tripped
        res[label + ("/OK" if ok else "/VIOLATION")] = \
            res.get(label + ("/OK" if ok else "/VIOLATION"), 0) + 1
        if not ok and len(bad) < 10:
            bad.append((label, cfg["id"], tripped, beats))
    for k in sorted(res):
        print("%-30s %d" % (k, res[k]), flush=True)
    for b in bad:
        print("  violation:", b, flush=True)


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 500))
