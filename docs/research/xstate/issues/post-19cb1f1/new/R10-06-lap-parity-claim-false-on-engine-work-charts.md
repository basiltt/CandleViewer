# `#209`'s "all three lanes agree at limits 1–25" is false on engine-work-only charts, and the gap grows with the limit

**Severity:** Medium (documentation / overstated guarantee about a safety control)
**Build:** `main` @ `19cb1f1` (PR #211, commit `4dbf86e`; unreleased 0.8.1). `__version__` still reports `0.8.0` — **key on the commit.**
**Environment:** CPython 3.13.7, Windows 11, fresh venv, neutral working directory. Polled to convergence, not sampled.

---

## Summary

**`#209` genuinely fixed the two shapes it measured.** On `rollback + onDone` the odd-limit asymmetry is gone: our independent sweep finds `sync == async_def == async_async` at every limit 1–25, and our own lap-parity harness went from 13 def-lane mismatches to 0. We verified that before writing this.

The problem is the **generalisation**. `CHANGELOG.md`, under `[Unreleased] — targeting 0.8.1`, `#201` entry, states without qualification: "with invokes armed at the end of the macrostep (#204) and the initial descent's settle work given seed standing, **all three lanes now agree at every limit, odd and even, on both the ping-pong and rollback shapes** -- pinned as a sweep." And earlier, in the `#210` entry: "the settle budget too; **all three lanes agree at limits 1–25**, odd and even, on both shapes. The #201 changelog sentence is corrected." On a chart consisting purely of engine work, **every swept limit differs**, with the gap widening as the limit rises.

## Observed

An `always` + zero-delay `raise` cycle. No timers, no delayed sends — so the `#206` carve-out (timer-paced self-sends are caller-`tick()`-driven on `SyncInterpreter`) does not apply, and **every step is engine work the chain budget is defined to charge**.

| `maxIterations` | sync laps | async laps | agree |
|---|---|---|---|
| 1 | 4 | 5 | **no** |
| 3 | 6 | 9 | **no** |
| 5 | 8 | 13 | **no** |
| 10 | 12 | 23 | **no** |
| 15 | 18 | 33 | **no** |
| 19 | 22 | 41 | **no** |
| 25 | 28 | 53 | **no** |

7/7 differ. Both lanes trip with `RunawayChainError` at every limit, so **nothing runs away** — the bound works. Async grows ~`2·mi+3`, sync ~`mi+3` on this shape (our wider fuzz over a related shape measured ~`3·mi+3` vs ~`2·mi+3`; the exact coefficients vary with the chart, the divergence does not).

At `maxIterations = 25` the same chart is permitted **roughly 89 % more work on one engine than on the other**. Our broader fuzz found 24 of 25 swept limits differing on a closely related shape, so this is not a corner.

The two engines charge the `always` settle step differently relative to `raise`.

## Why file a doc defect at Medium

The runaway budget is a **safety control**. A downstream reader sizing `maxIterations` against a worst-case work bound — which is exactly what the docs encourage — will treat a stated cross-engine equivalence as load-bearing. If the same chart and the same limit buy nearly twice the work on one engine, then a limit validated on the sync engine does not transfer to the async one, and the reader has no way to know that from the release notes.

This is compounded by a second, smaller issue in the same pin, which we have raised on the `#209` issue itself: the sweep tests two shapes, and **the paired `nested_invoke` shape is inert** — it never exits its initial state, so it fires exactly 2 calls at every limit 1–25 and never trips at all. It agrees across lanes because a constant agrees with itself. So the pin advertises two-shape coverage and delivers one.

### Test-quality footnote: the `nested_invoke` pin in `tests/test_round9_findings.py`

`TestServiceCallsIdenticalOnAllLanes.test_service_calls_identical_on_all_lanes` (around line 800) sweeps two shapes — `rollback_ondone` and `nested_invoke` — over `mi in (1, 2, 3, 4, 5, 7, 10, 15, 20, 25)`. The `_nested` config (line ~770) invokes `svc` in nested state `a.a`, `onDone` targets `a.b`, which invokes again and `onDone` targets back to `a.a`. On every engine and at every swept limit this fires exactly 2 service calls and the machine never leaves top-level state `a` — it can't trip `RunawayChainError` because the loop that would consume the budget never actually happens (the invoke's `onDone` handler never fires a second time). The assertion `sync_n == async_n` is checking `2 == 2` at every limit, which holds trivially regardless of whether the underlying budget-charging logic is symmetric. So the pin's "two shapes" claim is really "one live shape, one constant."

**Suggested fix:** make the nested shape structurally isomorphic to `rollback_ondone` — i.e. give the inner states an `always` bounce or a self-targeting re-invoke so each lap actually re-arms and re-fires the service, the way `rollback_ondone`'s `b: {"always": "a"}` does. Alternatively, assert `sync_n > 2` (or assert the call count grows with `mi`) alongside the parity check, so a future regression that makes the shape inert again fails loudly instead of silently passing.

## What we would ask for

Either:

- **narrow the claim** to the shapes actually measured — e.g. "on `rollback + onDone`, all three lanes agree at limits 1–25" — and note that engine-work-only charts may differ; or
- **make the settle charge symmetric** across the two engines, which would be the stronger fix and would make the general claim true.

Either is fine. What does not work is the current combination: a general guarantee, a pin that covers one shape, and a measurable counter-example at every limit.

We have had to write "do not rely on cross-engine budget equivalence as a safety property" into our own configuration guidance, which seems a shame given how close this is to holding.

## Standalone repro

Stdlib + `xstate_statemachine` only. Runs from any working directory. Exit 1 = claim overstated.

```python
"""R10-06 (STANDALONE): #209's "all three lanes agree at limits 1-25" is false
on engine-work-only charts, and the gap GROWS with the limit.

Exit 0 = every swept limit agrees across lanes (claim holds).
Exit 1 = any limit differs (claim overstated).
"""
from __future__ import annotations

import asyncio
import json
import sys

from xstate_statemachine import (
    create_machine,
    Interpreter,
    SyncInterpreter,
    MachineLogic,
)

LIMITS = (1, 3, 5, 10, 15, 19, 25)


def _cfg(mi: int) -> dict:
    # `always` bounces a <-> b; each entry raises, so every lap is engine work.
    return {
        "id": "w",
        "initial": "a",
        "maxIterations": mi,
        "states": {
            "a": {
                "entry": [{"type": "raise", "params": {"event": "GO"}}, "tick"],
                "on": {"GO": "b"},
            },
            "b": {"always": "a", "entry": ["tick"]},
        },
    }


def _machine(mi: int, counter: dict):
    def _tick(i, c, e, a=None):
        counter["n"] += 1

    return create_machine(
        json.loads(json.dumps(_cfg(mi))), logic=MachineLogic(actions={"tick": _tick})
    )


async def _async_laps(mi: int) -> tuple:
    c = {"n": 0}
    interp = Interpreter(_machine(mi, c))
    await interp.start()
    # Poll to convergence rather than sampling: stable count over 5 x 60 ms.
    last, stable = -1, 0
    for _ in range(60):
        await asyncio.sleep(0.06)
        if c["n"] == last:
            stable += 1
            if stable >= 5:
                break
        else:
            last, stable = c["n"], 0
    err = type(getattr(interp, "last_error", None)).__name__
    await interp.stop()
    return c["n"], err


def _sync_laps(mi: int) -> tuple:
    c = {"n": 0}
    interp = SyncInterpreter(_machine(mi, c))
    interp.start()
    err = type(getattr(interp, "last_error", None)).__name__
    interp.stop()
    return c["n"], err


async def main() -> int:
    diff = 0
    print(f"{'maxIter':<10}{'sync':<10}{'async':<10}{'agree':<8}errors")
    for mi in LIMITS:
        a, aerr = await _async_laps(mi)
        s, serr = _sync_laps(mi)
        ok = a == s
        diff += 0 if ok else 1
        print(f"{mi:<10}{s:<10}{a:<10}{('yes' if ok else 'NO'):<8}"
              f"sync={serr} async={aerr}")
    print()
    print("VERDICT:", "CLAIM OVERSTATED" if diff else "ok",
          f"({diff}/{len(LIMITS)} swept limits differ)")
    return 1 if diff else 0


if __name__ == "__main__":
    try:
        rc = asyncio.run(asyncio.wait_for(main(), 90.0))
    except asyncio.TimeoutError:
        print("WATCHDOG TIMEOUT")
        rc = 1
    sys.exit(rc)
```

### Actual output at `19cb1f1`

```
maxIter   sync      async     agree   errors
1         4         5         NO      sync=RunawayChainError async=RunawayChainError
3         6         9         NO      sync=RunawayChainError async=RunawayChainError
5         8         13        NO      sync=RunawayChainError async=RunawayChainError
10        12        23        NO      sync=RunawayChainError async=RunawayChainError
15        18        33        NO      sync=RunawayChainError async=RunawayChainError
19        22        41        NO      sync=RunawayChainError async=RunawayChainError
25        28        53        NO      sync=RunawayChainError async=RunawayChainError

VERDICT: CLAIM OVERSTATED (7/7 swept limits differ)
```
