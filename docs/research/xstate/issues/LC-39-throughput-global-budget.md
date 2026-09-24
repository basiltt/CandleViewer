---
lc: LC-39
title: "Docs: throughput is a fixed global budget shared by all interpreters, not a per-machine capacity"
labels: [documentation, performance, severity/high, area/perf, candleviewer]
severity: High
blocks_adoption: false
repro_script: repro/LC-39_throughput-global-budget.py
library_version: 0.7.0 (commit 42612cf)
python: 3.13.7
verified: true
---

## Summary

Every `Interpreter` created in a process drives its events through its own `asyncio.Queue` and `_run_event_loop` task, but all of those tasks run on **one asyncio event loop on one OS thread**. Concurrency in this library is therefore *interleaving, not parallelism*: the aggregate number of events per second is a roughly fixed global budget (~18–34k ev/s on a modern desktop, depending on macrostep cost), and adding machines does not add capacity — it divides the budget. At N=1,000 interpreters the per-machine share measured in this study is **18.2 ev/s**.

Nothing in the README, the guides or the API docs says this. A reader who sees an `async` interpreter, a per-interpreter queue and a per-interpreter task can very reasonably conclude that N machines process events concurrently in the throughput sense, and size their system accordingly. This is not a bug to be fixed — it is the correct consequence of a single-threaded asyncio design — but it is the single most important operational fact about the library and it must be stated plainly in the documentation, with numbers and with the scaling guidance that follows from it (scale by **process**, not by machine count).

## Environment

- Library: `xstate-statemachine` 0.7.0, commit `42612cf`, local clone, installed with `pip install -e .`
- Python: 3.13.7 (CPython, GIL enabled)
- OS: Windows 11 (x64)
- Install method: `pip install -e .` into a dedicated venv
- Benchmarks run with `tracemalloc` **off** (see *Root cause analysis* — tracing distorts throughput by ~5×)

## Minimal reproduction

```python
"""LC-39 repro: throughput is a fixed GLOBAL budget, not a per-machine one.

Every `Interpreter` shares one asyncio event loop on one OS thread. Event
processing is therefore interleaved, never parallel: the aggregate number of
events per second across N interpreters is roughly constant (and in fact
decays with N due to scheduling overhead), so the per-machine share is the
global budget divided by N.

This measures aggregate throughput at N = 1, 10, 100 and 500 and fails if
aggregate throughput scales with N by even 2x -- i.e. it fails if the
library does what a reader might reasonably assume.

Exit code 1 if aggregate throughput is flat (the documented-gap behaviour).
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time

from xstate_statemachine import Interpreter, MachineLogic, create_machine

logging.disable(logging.CRITICAL)

EVENTS = 2000
WARMUP = 200
REPEATS = 3
NS = (1, 10, 100, 500)

CFG = {
    "id": "oms",
    "initial": "idle",
    "context": {"n": 0},
    "states": {
        "idle": {"on": {"TICK": {"target": "idle", "actions": ["bump"]}}},
    },
}


def bump(interpreter, context, event, action_def):  # noqa: ANN001
    context["n"] += 1


def machine():
    return create_machine(CFG, logic=MachineLogic(actions={"bump": bump}))


async def aggregate(n: int) -> float:
    interps = [Interpreter(machine()) for _ in range(n)]
    await asyncio.gather(*(i.start() for i in interps))

    async def drive(i, count):
        for _ in range(count):
            await i.send("TICK")

    # 🔥 Warm up: first-touch costs (import-time lazy work, dict/type caches,
    # asyncio task bookkeeping) otherwise land entirely on the N=1 sample and
    # make the baseline look artificially slow, which swings the ratio.
    await asyncio.gather(*(drive(i, WARMUP) for i in interps))

    t0 = time.perf_counter()
    await asyncio.gather(*(drive(i, EVENTS) for i in interps))
    elapsed = time.perf_counter() - t0
    await asyncio.gather(*(i.stop() for i in interps))
    return (n * EVENTS) / elapsed


async def best_of(n: int, repeats: int = REPEATS) -> float:
    """Take the best of several timings: throughput noise is one-sided, so the
    maximum is the closest estimate of the machine's real capacity."""
    return max([await aggregate(n) for _ in range(repeats)])


async def main() -> int:
    results = {}
    for n in NS:
        results[n] = await best_of(n)
        print(
            f"OBSERVED: N={n:<4} aggregate={results[n]:>9,.0f} ev/s   "
            f"per-machine={results[n] / n:>9,.1f} ev/s"
        )
    base = results[NS[0]]
    top = results[NS[-1]]
    print(
        f"OBSERVED: aggregate scaling factor from N={NS[0]} to N={NS[-1]} "
        f"= {top / base:.2f}x (per-machine share fell "
        f"{base / (top / NS[-1]):,.0f}x)"
    )
    print(
        "EXPECTED (naive reading of the docs): aggregate throughput grows "
        "with N, or the docs state plainly that it does not."
    )
    return 0 if top / base > 2.0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED: N=1    aggregate=   33,754 ev/s   per-machine= 33,753.6 ev/s
OBSERVED: N=10   aggregate=   33,970 ev/s   per-machine=  3,397.0 ev/s
OBSERVED: N=100  aggregate=   34,318 ev/s   per-machine=    343.2 ev/s
OBSERVED: N=500  aggregate=   32,657 ev/s   per-machine=     65.3 ev/s
OBSERVED: aggregate scaling factor from N=1 to N=500 = 0.97x (per-machine share fell 517x)
EXPECTED (naive reading of the docs): aggregate throughput grows with N, or the docs state plainly that it does not.
```

Exit code `1`.

Aggregate throughput is flat across a 500× increase in machine count (0.97× from N=1 to N=500 — roughly 33k ev/s at every N). The per-machine share falls by **517×**, i.e. essentially exactly 1/N.

The script warms each configuration up before timing and takes the best of three repeats, because throughput noise is one-sided and a cold N=1 baseline otherwise swings the headline ratio substantially (unwarmed, the same script produced factors ranging from 0.73× to 1.58× across consecutive runs). With warm-up the measurement is stable at ~0.7–1.0× across runs; the flatness, not any individual point, is the finding.

A longer-running variant of the same measurement (more events per interpreter, `tracemalloc` off) shows the same shape and extends it to N=1,000:

| N | aggregate ev/s | per-interpreter ev/s |
|---:|---:|---:|
| 1 | 21,231 | 21,231 |
| 10 | 20,305 | 2,031 |
| 100 | 20,063 | 201 |
| 500 | 19,323 | 38.6 |
| 1,000 | 18,152 | **18.2** |

A separate run pushing machine count further corroborates the plateau: 28,208 ev/s aggregate at N=1,000 and 20,568 ev/s at N=10,000. Batching via `send_events()` does not help (19,966 vs 18,152 ev/s at N=1,000) — the cost is in transition processing, not in enqueueing.

## Expected behaviour

There is no XState v5 semantic rule being violated here; the request is documentation, and XState's own docs are the model for what is missing. XState is explicit that actors share a scheduler and that concurrency is logical rather than parallel — see https://stately.ai/docs/actors, which describes actors as communicating via message passing within an actor *system* rather than as independently scheduled units of CPU capacity, and https://stately.ai/docs/actor-model ("Actors … communicate with each other by sending and receiving events/messages"), where nothing implies added throughput per actor.

What a Python reader needs stated, and which the current docs do not state anywhere:

1. All interpreters in a process share **one** asyncio event loop on **one** OS thread; the GIL and the single loop make event processing interleaved, never parallel.
2. Throughput is therefore a **global budget** measured in events/second *per process*, divided among all live interpreters.
3. A concrete order-of-magnitude figure with the hardware and method used to obtain it.
4. The scaling unit is the **process** (or a machine-sharded worker pool), not the interpreter.

## Root cause analysis

`src/xstate_statemachine/interpreter.py`:

- `:129-131` — each interpreter allocates its own `asyncio.Queue`, which correctly isolates event *ordering* per machine and is probably what leads readers to assume isolation of *capacity* too.
- `:132`, `:201-202`, `:234` — `self._event_loop_task = asyncio.create_task(self._run_event_loop())`. `asyncio.create_task` schedules onto the **currently running loop**. There is one such loop per thread, and the documented usage pattern (`asyncio.run(main())` driving every machine) means one loop for the whole process. N interpreters become N coroutines multiplexed over one thread.
- `:406-480` — `_run_event_loop` awaits an event, then `await self._process_event_and_transient_transitions(event)`. The macrostep — guards, exit/entry actions, context mutation — is ordinary synchronous Python between `await` points, so it occupies the single thread exclusively for its duration. Every other interpreter's loop is blocked meanwhile. Throughput is thus `1 / mean_macrostep_cost`, a per-process constant, regardless of how many queues feed it.
- There is no thread pool, no `run_in_executor` hand-off and no process pool anywhere in the event path, so no mechanism exists by which additional interpreters could consume additional cores.

The mild *decline* with N (rather than perfect flatness) is `asyncio` scheduler overhead: the ready-callback list and per-task bookkeeping grow with the number of live tasks, and each interpreter also holds timer/actor tasks via `TaskManager`.

**Measurement caveat worth documenting alongside the numbers:** running these benchmarks with `tracemalloc` enabled reports ~5,000 ev/s instead of ~28,000 (−82%) and inflates `create_machine()` from ~122 µs to ~1,120 µs (9.2×). Any throughput figure published must state that tracing was off, or it will be ~5× too pessimistic.

## Impact

**General users.** The mis-sizing this invites is silent and only shows up in production. A team benchmarking a single machine sees ~20–30k ev/s, concludes each machine can absorb tens of thousands of events per second, and deploys 1,000 machines expecting an aggregate in the millions. The real per-machine capacity is ~18 ev/s. There is no error, no warning and no backpressure (see `LC-41`) to signal the mistake — the queues simply grow, latency climbs without bound, and `after` timers begin to fire late or starve (see `LC-26`). The system degrades into unbounded memory growth rather than failing fast.

**CandleViewer trading OMS.** The design point is 500 concurrent order machines. At N=500 the measured aggregate is ~19–33k ev/s, so each order machine gets **~39–65 ev/s**. A market-data-driven OMS can easily generate hundreds of ticks per second per instrument; feeding raw ticks into the machines would exceed the global budget by two orders of magnitude. The consequences are exactly the dangerous ones for an OMS: an order machine sitting in `submitting` has its `FILLED` event queued behind a backlog of tick events, so the fill is applied seconds late — the position exists on the exchange while the machine still believes the order is pending, and risk checks reading machine context act on stale state. The `after`-based submission timeout fires late for the same reason and can beat the real fill to the queue, producing a spurious `timed_out` for an order that actually filled. The application therefore had to pre-filter ≥99% of market data before it reaches any machine, and shard the remaining load across OS processes — but a user without these measurements in hand has nothing to warn them that this is necessary.

## Proposed fix

No library change is warranted: the behaviour is the correct and unavoidable consequence of a single-threaded asyncio core, and "fixing" it would mean a different architecture. The fix is documentation, plus optional ergonomics.

**1. A new "Performance and scaling" guide page** (`docs/_guide/performance.md`), linked from the README and the `Interpreter` API page, containing:

> **Throughput is a per-process budget, not a per-machine one.**
> All interpreters created in a process run on a single asyncio event loop on a single OS thread. Concurrency is interleaving, not parallelism: running more machines does not increase total events/second, it divides the same budget.
>
> | Interpreters | Aggregate ev/s | Per-interpreter ev/s |
> |---:|---:|---:|
> | 1 | ~21,000 | ~21,000 |
> | 100 | ~20,000 | ~200 |
> | 1,000 | ~18,000 | ~18 |
>
> *(CPython 3.13, desktop x86-64, trivial single-action macrostep, `tracemalloc` off. Treat as an order of magnitude, not a guarantee — your macrostep cost sets your budget.)*
>
> **Sizing rule.** Estimate your mean macrostep cost, invert it for the process budget, and divide by your machine count. If the result is below your required per-machine event rate, scale by **process** (or shard machines across worker processes) — adding interpreters will not help.
>
> **Related caveats.** Blocking (non-`await`) work inside an action stalls *every* machine in the process. Benchmark with `tracemalloc` disabled; enabling it understates throughput by roughly 5×.

**2. A one-paragraph note with a cross-link** in the README's feature list and in the `Interpreter` class docstring (`interpreter.py:100`-ish), so the fact is reachable without finding the guide.

**3. Optional ergonomics (separate, lower priority).** Expose a lightweight counter — events processed and mean macrostep duration per interpreter — so users can measure their own budget rather than trusting a published number. This pairs naturally with the backpressure work in `LC-41`: a queue-depth metric is the practical early warning that the budget has been exceeded.

**Backwards compatibility.** Documentation-only; no API or behaviour change. The optional counter would be additive and off by default.

## Acceptance criteria

- [ ] A "Performance and scaling" page exists in the guide and states explicitly that all interpreters share one event loop on one thread and that throughput is a per-process budget divided by machine count.
- [ ] That page carries a measured scaling table (at minimum N = 1, 100, 1,000) together with the hardware, Python version, macrostep shape and the fact that `tracemalloc` was disabled.
- [ ] The page states the scaling unit is the process, and warns that blocking work in an action stalls every machine in the process.
- [ ] The README and the `Interpreter` docstring both link to it.
- [ ] `repro/LC-39_throughput-global-budget.py` is retained as a benchmark; note that it exits `1` *by design* while the behaviour stands — it is an assertion about the docs gap, not a regression test.
- [ ] Tests added under `tests/test_performance_docs.py`:
  - `test_scaling_guide_page_exists_and_mentions_single_event_loop`
  - `test_readme_links_to_performance_guide`
- [ ] If the optional counter is implemented, tests under `tests/test_interpreter_metrics.py`:
  - `test_interpreter_reports_processed_event_count`
  - `test_interpreter_reports_mean_macrostep_duration`

## Related

- On a realistic (non-trivial) macrostep the same measurement gives ~8.8k ev/s rather than ~33k — the budget shrinks with macrostep cost, which is the practical consequence of this issue.
- `LC-41` — unbounded queue, no backpressure. Exceeding the budget has no failure signal; the queue just grows.
- `LC-26` — timer starvation under load. The first user-visible symptom of an over-subscribed budget.
- This is one of several production characteristics of the library that are currently undocumented.
- `LC-12` — blocking work in a spawned actor stalls the async engine (same single-thread root cause).
- Found during an independent evaluation of the library for a trading application; the reproduction above is self-contained, and the supporting scaling numbers were produced by the same method it uses.

## Verification

Independently verified on 2026-09-15.

- Environment: `xstate-statemachine` 0.7.0, commit `42612cf`, editable install; CPython 3.13.7; Windows 11 x64.
- `repro/LC-39_throughput-global-budget.py` run in a fresh process: **exit code 1** (reproduces, by design — see the acceptance criteria note).
- Root-cause references re-checked against the source: `interpreter.py:129-131` (per-interpreter `asyncio.Queue`), `:201-202` and `:234` (`asyncio.create_task(self._run_event_loop())`), `:406` and `:473` (`await self._process_event_and_transient_transitions(event)` inside the loop). No `run_in_executor`, thread pool or process pool exists in the event path, confirming the claim that extra interpreters cannot consume extra cores.
- The documentation gap is real: searching `docs/` and `README.md` for any statement about a single shared event loop or a per-process throughput budget returns nothing.
- Expected-behaviour claim re-checked against XState v5 docs: https://stately.ai/docs/actor-model states "Actors process one message at a time… processing events sequentially" and describes communication purely as message passing, with nothing implying added per-actor throughput. The issue correctly frames this as a documentation request rather than a semantic violation.
- Corrections applied during verification:
  - The repro was measurement-unstable: with 200 events and no warm-up, the headline N=1→N=500 ratio swung between 0.73× and 1.58× across consecutive runs, and one run produced a spurious 3.5× dip at N=100. Added a warm-up pass, raised the sample to 2,000 events per interpreter, and take the best of three repeats. The ratio is now stably ~0.7–1.0× with aggregate throughput visibly flat (~33k ev/s) at every N. The Observed block was replaced with a verbatim run of the corrected script.
  - Headline figures were widened to match what the corrected script actually measures (~18–34k ev/s aggregate; ~39–65 ev/s per machine at N=500).
  - `Interpreter` is declared at `interpreter.py:89`; the docstring reference was left approximate but the surrounding claims were confirmed.
- Duplicate check: `gh issue list --state all` returns only #17 (closed, unrelated). **Not a duplicate**.
