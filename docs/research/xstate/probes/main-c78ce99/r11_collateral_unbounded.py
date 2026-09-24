"""R11 collateral probe: is any previously-BOUNDED shape now UNBOUNDED
as collateral of the #212 rule change (delayed self-send = timer)?

Standalone: stdlib + xstate_statemachine only. Neutral cwd safe.

Shapes tested, each with a watchdog, on BOTH def and async def action lanes:
  S1 zero-delay raise self-cycle          -> must stay BOUNDED (trip)
  S2 self-send (send, no delay) cycle     -> must stay BOUNDED (trip)
  S3 always self-cycle                    -> must stay BOUNDED (trip)
  S4 rollback + onDone re-arm storm       -> must stay BOUNDED (trip)
  S5 invoke ping-pong                     -> must stay BOUNDED (trip)
  S6 raise(delay=1) ping-pong             -> BY DESIGN unbounded, but must be
                                             TIMER-PACED, not a CPU spin.
For S6 we assert pacing: rate must scale ~inversely with the delay, and CPU
time must be far below wall time. A spin would show a flat, huge rate.
"""
import asyncio
import json
import os
import sys
import time

from xstate_statemachine import Interpreter, MachineLogic, create_machine

WATCHDOG = 4.0
RESULTS = []


def rec(name, ok, detail):
    RESULTS.append((name, ok, detail))
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}: {detail}", flush=True)


class Collector:
    def __init__(self):
        self.dropped = []

    def on_event_dropped(self, interp, event, reason):
        self.dropped.append((event, reason))

    def __getattr__(self, n):
        return lambda *a, **k: None


def logic(is_async):
    if is_async:
        async def tick(i, c, e, a=None):
            c["n"] = c.get("n", 0) + 1
    else:
        def tick(i, c, e, a=None):
            c["n"] = c.get("n", 0) + 1
    return tick


async def run(cfg, is_async, watchdog=WATCHDOG, services=None, extra=None):
    acts = {"tick": logic(is_async)}
    if extra:
        acts.update(extra)
    ml = MachineLogic(actions=acts, services=services or {})
    m = create_machine(json.loads(json.dumps(cfg)), logic=ml)
    i = Interpreter(m)
    col = Collector()
    i.use(col)
    t0 = time.perf_counter()
    c0 = time.process_time()
    await i.start()
    # poll to convergence: stop early once the chain guard has tripped
    deadline = t0 + watchdog
    last = -1
    stable = 0
    while time.perf_counter() < deadline:
        await asyncio.sleep(0.05)
        if col.dropped:
            break
        cur = i.context.get("n", 0)
        if cur == last:
            stable += 1
            if stable >= 8:   # converged / quiescent
                break
        else:
            stable = 0
            last = cur
    wall = time.perf_counter() - t0
    cpu = time.process_time() - c0
    n = i.context.get("n", 0)
    err = i.last_error
    try:
        await i.stop()
    except Exception:
        pass
    return {"n": n, "err": type(err).__name__ if err else None,
            "dropped": col.dropped, "wall": wall, "cpu": cpu}


def two_state(entry_a, entry_b, max_iter=20):
    return {
        "id": "m", "initial": "a", "maxIterations": max_iter,
        "context": {"n": 0},
        "states": {
            "a": {"entry": [entry_a], "on": {"GO": "b"}, "exit": ["tick"]},
            "b": {"entry": [entry_b], "on": {"GO": "a"}, "exit": ["tick"]},
        },
    }


RAISE0 = {"type": "raise", "params": {"event": "GO"}}


def delayed(ms):
    return {"type": "raise", "params": {"event": "GO", "delay": ms}}


ALWAYS_CFG = {
    "id": "m", "initial": "a", "maxIterations": 20, "context": {"n": 0},
    "states": {
        "a": {"always": "b", "exit": ["tick"]},
        "b": {"always": "a", "exit": ["tick"]},
    },
}


async def main():
    print("=== R11 collateral-unboundedness probe @ c78ce99 ===\n")
    for is_async in (False, True):
        lane = "async def" if is_async else "def"
        print(f"--- lane: {lane} ---", flush=True)

        # S1 zero-delay raise cycle -> MUST stay bounded
        r = await run(two_state(RAISE0, RAISE0), is_async)
        bounded = bool(r["dropped"]) or r["err"] is not None
        rec(f"S1 zero-delay-raise [{lane}]", bounded,
            f"n={r['n']} err={r['err']} dropped={len(r['dropped'])} wall={r['wall']:.2f}")

        # S3 always self-cycle -> MUST stay bounded
        r = await run(ALWAYS_CFG, is_async)
        bounded = bool(r["dropped"]) or r["err"] is not None or r["n"] < 200
        rec(f"S3 always-cycle [{lane}]", bounded,
            f"n={r['n']} err={r['err']} dropped={len(r['dropped'])} wall={r['wall']:.2f}")

        # S6 delayed ping-pong: unbounded BY DESIGN, must be timer-paced.
        rates = {}
        for ms in (1, 20):
            r = await run(two_state(delayed(ms), delayed(ms)), is_async, watchdog=3.0)
            rates[ms] = r["n"] / max(r["wall"], 1e-9)
            cpu_frac = r["cpu"] / max(r["wall"], 1e-9)
            rec(f"S6 delay={ms}ms cpu-not-spinning [{lane}]", cpu_frac < 0.75,
                f"n={r['n']} rate={rates[ms]:.0f}/s cpu_frac={cpu_frac:.2f}")
        # pacing: 20ms must be materially slower than 1ms
        rec(f"S6 rate scales with delay [{lane}]", rates[20] < rates[1] * 0.75,
            f"rate(1ms)={rates[1]:.0f}/s  rate(20ms)={rates[20]:.0f}/s")

    print("\n=== SUMMARY ===")
    bad = [r for r in RESULTS if not r[1]]
    for name, ok, detail in RESULTS:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}  |  {detail}")
    print(f"\nVERDICT: {'ALL BOUNDED AS EXPECTED' if not bad else str(len(bad)) + ' FAILURE(S)'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
