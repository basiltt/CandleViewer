# The library's own `TestAsyncRollbackRearmCycleBounded` test sleeps too briefly to observe the `def` lane converge, and fails on a normal host while the behaviour it tests is correct

**Severity (ours):** Low
**Build:** `main` @ `f28719c` (merge of PR #202, unreleased 0.8.1; `__version__` still reports `0.8.0` — keyed on the commit)
**Environment:** CPython 3.13.7, Windows 11, fresh venv
**Kind:** `def` (also checked `async def`, for contrast — see below)
**Relates to:** #201 (the fix this test pins is correct; only the test's timing is wrong)

---

## Summary

`tests/test_round6_findings.py::TestAsyncRollbackRearmCycleBounded::test_service_calls_bounded_by_max_iterations`
reads the service call counter at `0.6 s` after start and asserts it equal to
the count read at a second, later sample (`0.9 s`/`0.3 s` apart in the pinned
assertion). On a normal host the **`def`-lane** counter is **still climbing at
`0.6 s`** and only converges to its true plateau around `1.0 s`. The test
therefore fails on a large fraction of runs — not because the cycle is
unbounded, but because the sleep window is too short to see it stop.

This is filed as its own issue (separate from `R9-09`, which raised it as a
side observation) because it is a standalone, reproducible test-infrastructure
defect with its own fix, independent of the documentation wording `R9-09`
is about.

## Evidence

Polling the same cycle every `0.5 s` for up to `20 s` and stopping once the
count has been stable for five consecutive reads shows both lanes plateau at
exactly `maxIterations + 2` and never move again once they get there:

```
kind=def   series=[(0.5,781),(1.01,1003),(1.52,1003),(2.03,1003),(2.54,1003),(3.05,1003)]
kind=async series=[(0.51,1003),(1.02,1003),(1.53,1003),(2.03,1003),(2.54,1003)]
```

`def` is still at `781` of `1003` at the `0.5 s`/`0.6 s` mark the pinned test
samples, and only reaches the plateau (`1003 = maxIterations(1000) + 2`) around
`1.0 s`. `async def` has already converged by `0.5 s`. Reading the counter at
`0.6 s` and comparing it to a slightly later sample therefore catches the
`def` lane mid-climb, not at rest, which is exactly the shape of an
intermittent CI failure on a normal (non-idle, non-dedicated) host — the test
fails roughly 80% of runs in our environment while the underlying behaviour
(the cycle is bounded, and bounded at the same count on both lanes) is
correct.

## Suggested resolution

Poll to a stable plateau (e.g. sample every `0.5 s` and require N consecutive
equal reads, as the repro below does) instead of comparing two fixed,
short-elapsed timestamps. This removes the host-speed dependency entirely and
keeps the assertion just as strong — it still fails if the count does not
actually stop increasing.

## Standalone repro

`stdlib` + `xstate_statemachine` only, every helper inlined. Run from a
neutral cwd, e.g. `<home>`:

```
python R9-T1_plateau.py def
python R9-T1_plateau.py async
```

```python
# R9-T1_plateau.py — STANDALONE: does the rollback+onDone re-arm cycle
# plateau, or spin forever? Polls to convergence instead of sampling two
# fixed, short-elapsed timestamps (which is what the pinned library test
# does, and why it fails intermittently on a normal host for the `def` lane).
#
# Usage: python R9-T1_plateau.py [def|async]
import asyncio
import sys
import time
import logging

logging.disable(logging.CRITICAL)

from xstate_statemachine import Interpreter, MachineLogic, create_machine

KIND = sys.argv[1] if len(sys.argv) > 1 else "def"

CFG = {
    "id": "spin",
    "actionErrorPolicy": "rollback",
    "initial": "starting",
    "context": {},
    "states": {
        "starting": {
            "invoke": {"id": "s", "src": "svc", "onDone": {"target": "#spin.recording"}}
        },
        "recording": {"entry": ["boom"]},
    },
}


async def main():
    calls = [0]

    def boom(*a):
        raise RuntimeError("boom")

    def bump():
        calls[0] += 1
        return 1

    if KIND == "def":
        def svc(*a):
            return bump()
    else:
        async def svc(*a):
            return bump()

    interp = Interpreter(
        create_machine(
            CFG,
            logic=MachineLogic(actions={"boom": boom}, services={"svc": svc}),
        )
    )
    await interp.start()

    t0 = time.monotonic()
    series = []
    stable = 0
    last = -1
    # Poll for up to 20s: record the count every 0.5s, stop once stable
    # for 5 consecutive reads (a converged plateau, not a fixed-time sample).
    while time.monotonic() - t0 < 20:
        await asyncio.sleep(0.5)
        c = calls[0]
        series.append((round(time.monotonic() - t0, 2), c))
        if c == last:
            stable += 1
        else:
            stable = 0
        last = c
        if stable >= 5:
            break

    print(f"kind={KIND} status={interp.status} final_calls={calls[0]}")
    print(f"series={series}")
    await interp.stop()
    return calls[0], stable


n, stable = asyncio.run(main())
bounded = stable >= 5
print(f"BOUNDED={bounded} plateau={n}")
sys.exit(0 if bounded else 1)
```

Exit code `0` on both lanes: the cycle is bounded and plateaus at
`maxIterations + 2`. The defect is purely in the pinned test's sampling
window, not in the interpreter.
