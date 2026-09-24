"""D2b -- pin the exact run-to-run instability D1 found.

D1's only divergent digest is `receipts`, 4th field (`deferred`). This runs the
SAME script several times and prints, per run, the set of send-indices whose
receipt claimed `deferred=True`, plus the event type at that index. If the sets
differ between runs of an identical deterministic script, the flag is
nondeterministic.
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dmachine import Recorder, build, make_script  # noqa: E402
from xstate_statemachine import Interpreter, SyncInterpreter  # noqa: E402
from xstate_statemachine.clock import SimulatedClock  # noqa: E402


async def arun(script):
    rec = Recorder()
    clock = SimulatedClock()
    interp = Interpreter(build(rec), clock=clock)
    await interp.start()
    flags, types, leak = [], [], []
    k = 0
    for step in script:
        if step[0] == "tick":
            await clock.increment(step[1])
            continue
        r = await interp.send(step[1], wait=True, **step[2])
        if r.deferred:
            flags.append(k)
            types.append(step[1])
        leak.append(len(interp._deferred_this_step))
        k += 1
    out = (flags, types, leak[-1], interp.deferred_count)
    await interp.stop()
    return out


def srun(script):
    rec = Recorder()
    clock = SimulatedClock()
    interp = SyncInterpreter(build(rec), clock=clock)
    interp.start()
    flags, types = [], []
    k = 0
    for step in script:
        if step[0] == "tick":
            clock.increment(step[1])
            continue
        r = interp.send(step[1], wait=True, **step[2])
        if r.deferred:
            flags.append(k)
            types.append(step[1])
        k += 1
    out = (flags, types, len(interp._deferred_this_step), interp.deferred_count)
    interp.stop()
    return out


def report(name, results):
    base = results[0][0]
    print(f"\n=== {name} ===")
    for n, (flags, types, leak, real) in enumerate(results):
        mark = "" if flags == base else "   <-- DIFFERS FROM RUN 0"
        print(
            f" run {n}: {len(flags)} deferred-flagged receipts; "
            f"_deferred_this_step={leak}; deferred_count={real}{mark}"
        )
    stable = all(r[0] == base for r in results)
    print(f" stable across {len(results)} runs: {stable}")
    if not stable:
        for n, (flags, types, _, _) in enumerate(results):
            if flags != base:
                a, b = set(base), set(flags)
                print(f"   run0-only indices: {sorted(a - b)[:15]}")
                print(f"   run{n}-only indices: {sorted(b - a)[:15]}")
                only = sorted(b - a)[:5]
                for i in only:
                    print(
                        f"     idx {i}: event {results[n][1][flags.index(i)]}"
                    )
                break
    # Which event types ever get flagged?
    seen = {}
    for flags, types, _, _ in results:
        for t in types:
            seen[t] = seen.get(t, 0) + 1
    print(f" flagged event types (count over all runs): {seen}")
    return stable


if __name__ == "__main__":
    script = make_script(600)
    ar = [asyncio.run(arun(script)) for _ in range(6)]
    report("async x6, identical script", ar)
    sr = [srun(script) for _ in range(6)]
    report("sync x6, identical script", sr)
