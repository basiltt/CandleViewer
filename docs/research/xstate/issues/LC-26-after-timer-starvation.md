---
lc: LC-26
title: "Perf: `after` timers degrade catastrophically under event-loop load"
labels: [performance, severity/high, area/timers, candleviewer]
severity: High
blocks_adoption: false
repro_script: repro/LC-26_after_timer_starvation.py
library_version: 0.7.0 (commit 42612cf)
python: 3.13.7
verified: true
---

## Summary

`after` deadlines are implemented as `asyncio.sleep` tasks (`interpreter.py:1011`) created on the same event loop that drains every interpreter's event queue. They therefore inherit that loop's scheduling latency in full. With 100 busy interpreters on the loop, a **10 ms** `after` timer fires **+197 ms** late and a **100 ms** timer fires **+212 ms** late — the absolute error is essentially independent of the nominal delay, which is the signature of event-loop starvation rather than of clock granularity. Broader benching shows the same shape scaling to **+2,250 ms at 500 busy interpreters**.

A 10 ms timer that fires ~200 ms late is not a timer. Nothing in the documentation mentions this characteristic, so users discover it in production, under load, which is exactly when timed transitions (deadlines, watchdogs, retry backoffs) matter most.

## Environment

- Library: xstate-statemachine 0.7.0, commit `42612cf` (local clone, `pip install -e .`)
- Python: 3.13.7
- OS: Windows-11-10.0.26200-SP0 (note: Windows' ~15.6 ms timer granularity is a floor and explains the *idle* error, not the loaded error)
- Install method: editable install into a dedicated venv

## Minimal reproduction

```python
"""LC-26 repro: `after` timers degrade catastrophically under event-loop load.

`after` deadlines are plain `asyncio.sleep` tasks scheduled on the same loop
that drains every interpreter's event queue. They therefore inherit the
loop's scheduling latency: a 10 ms timer measured against N busy
interpreters fires hundreds of milliseconds late, and the absolute error is
roughly independent of the nominal delay -- the signature of event-loop
starvation rather than of clock granularity.

Exit code 1 if the loaded-case error exceeds the tolerance.
"""

from __future__ import annotations

import asyncio
import logging
import statistics
import time

from xstate_statemachine import Interpreter, MachineLogic, create_machine

logging.disable(logging.CRITICAL)

DELAYS_MS = (10, 100)
LOAD = 100
SAMPLES = 15
TOLERANCE_MS = 50.0


def timer_machine(delay_ms: int):
    cfg = {
        "id": f"t{delay_ms}",
        "initial": "wait",
        "context": {"fired_at": 0.0},
        "states": {
            "wait": {"after": {delay_ms: {"target": "fired"}}},
            "fired": {"entry": ["stamp"], "type": "final"},
        },
    }

    def stamp(i, c, e, a):  # noqa: ANN001
        c["fired_at"] = time.perf_counter()

    return create_machine(cfg, logic=MachineLogic(actions={"stamp": stamp}))


BUSY_CFG = {
    "id": "b",
    "initial": "s",
    "context": {"n": 0},
    "states": {"s": {"on": {"P": {"actions": ["bump"]}}}},
}


def bump(i, c, e, a):  # noqa: ANN001
    c["n"] += 1


async def measure(delay_ms: int) -> float:
    errs = []
    for _ in range(SAMPLES):
        interp = Interpreter(timer_machine(delay_ms))
        t0 = time.perf_counter()
        await interp.start()
        deadline = t0 + delay_ms / 1000.0 + 10.0
        while interp.context["fired_at"] == 0.0:
            if time.perf_counter() > deadline:
                break
            await asyncio.sleep(0.0005)
        fired = interp.context["fired_at"]
        await interp.stop()
        if fired:
            errs.append(((fired - t0) - delay_ms / 1000.0) * 1000.0)
    return statistics.median(errs) if errs else float("nan")


async def churn(interp, stop: asyncio.Event) -> None:  # noqa: ANN001
    while not stop.is_set():
        for _ in range(20):
            await interp.send("P")
        await asyncio.sleep(0)


async def scenario(load: int) -> dict:
    stop = asyncio.Event()
    busy, tasks = [], []
    for _ in range(load):
        m = create_machine(BUSY_CFG, logic=MachineLogic(actions={"bump": bump}))
        busy.append(await Interpreter(m).start())
    tasks = [asyncio.create_task(churn(b, stop)) for b in busy]
    out = {d: await measure(d) for d in DELAYS_MS}
    stop.set()
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    for b in busy:
        await b.stop()
    return out


async def main() -> int:
    idle = await scenario(0)
    loaded = await scenario(LOAD)
    ok = True
    for d in DELAYS_MS:
        print(f"OBSERVED {d:>4} ms timer, idle loop        = {idle[d]:+9.1f} ms error")
        print(f"OBSERVED {d:>4} ms timer, {LOAD} busy actors = {loaded[d]:+9.1f} ms error")
        if loaded[d] > TOLERANCE_MS:
            ok = False
    print(f"EXPECTED every case within +{TOLERANCE_MS:.0f} ms of nominal")
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED   10 ms timer, idle loop        =      +5.7 ms error
OBSERVED   10 ms timer, 100 busy actors =    +197.3 ms error
OBSERVED  100 ms timer, idle loop        =     +11.1 ms error
OBSERVED  100 ms timer, 100 busy actors =    +211.9 ms error
EXPECTED every case within +50 ms of nominal
RESULT: FAIL
```

Exit code `1`. (This is a timing measurement, so the absolute numbers move run to run; across repeated runs on this machine the loaded error has landed between roughly +190 ms and +240 ms for both delays. The *shape* — loaded error ≈ 20–40× the tolerance, and essentially identical for 10 ms and 100 ms — is stable and is the point.)

The diagnostic reading is in the two loaded numbers: **+197 ms and +212 ms are, for practical purposes, the same number.** If this were clock granularity or per-timer overhead the error would scale with, or be dominated by, the nominal delay. A near-constant additive error across a 10× range of delays means the timer callback is waiting for the *loop*, not for the clock. The idle column confirms the baseline is fine (+5.7 / +11.1 ms, consistent with Windows' ~15.6 ms timer tick).

Corroborating measurements from a separate timer bench on the same machine: idle error +6 to +16 ms; 100 busy interpreters ≈ +500 ms; **500 busy interpreters ≈ +2,250 ms for a 10 ms timer**, and approximately the same absolute error at 100 ms and at 1 s. A separate probe independently observed 5 ms `after` delays drifting ~10.9 ms p50 with an *idle* loop.

## Expected behaviour

XState documents delayed transitions as deadlines the interpreter is responsible for honouring: <https://stately.ai/docs/delayed-transitions> — "**Delayed transitions** are transitions that are triggered after a set amount of time. Delayed transitions are useful for building timeouts and intervals into your application logic. If another event occurs before the end of the timer, the transition doesn't complete." The contract is about *when* the transition happens, and a library is expected to honour it to within the resolution of its clock, not to within the convenience of its scheduler.

XState makes this tractable by treating the clock as an injectable dependency: the actor system is constructed with a `clock` (`createSystem(rootActor, { clock, logger })`, and the system exposes `_clock`; `Clock` is the two-method interface `{ setTimeout, clearTimeout }` — see `packages/core/src/system.ts` in the XState repo), and `createActor(logic, { clock })` accepts one. XState also ships `SimulatedClock`, so delayed transitions can be driven by virtual time in tests. The same module shows that XState's scheduler keeps its pending delayed sends in `system._snapshot._scheduledEvents`, i.e. scheduled timers are first-class, persistable state rather than anonymous sleep tasks. This library has neither an injectable clock (see LC-27) nor a scheduler isolated from the event queue, so a user has no lever at all: no way to prioritise timers, no way to measure the drift from inside, no way to test against it deterministically.

Two things are reasonable to expect, and the second is the minimum:

1. Timer expiry is scheduled independently of event-queue drain, so timer latency degrades with *loop* saturation rather than with *this library's own* queue depth; or
2. the starvation characteristic, its magnitude, and the load at which it appears are **documented**, so users can decide whether `after` is usable for their deadlines before they build on it.

## Root cause analysis

`src/xstate_statemachine/interpreter.py`:

- `:1027-1040` — `_after_timer()` does `asyncio.create_task(self._after_timer_task(delay_sec, event))` and registers it with the `TaskManager` for cancellation on state exit. The task goes onto the default running loop; there is no dedicated executor, no thread, no priority.
- `:999-1024` — `_after_timer_task()` is `await asyncio.sleep(delay_sec)` followed by `await self.send(event)`.

This gives **two** serialised sources of delay, which is why the error is additive rather than proportional:

1. `asyncio.sleep(delay_sec)` resolves only when the loop next runs its ready queue. Every other interpreter's `_run_event_loop` (`:427`) is a coroutine on that same loop, each resuming on every `await self._event_queue.get()`; 100 of them under churn means the loop's ready queue is long and the timer callback waits behind it.
2. When the sleep *does* resolve, the timer does not fire the transition — it calls `send()`, which appends an `AfterEvent` to the *back of this interpreter's own event queue* (`:375`). The timer event then queues behind every ordinary event already pending. A machine that is busy is therefore penalised twice: once by the loop, once by its own backlog.

Point 2 is the more interesting half and is independent of load-shedding: even on an unloaded loop, an `after` deadline on a machine with a deep inbox will not be honoured until that inbox drains, because the deadline is delivered as an ordinary event with no priority. SCXML separates the *internal* event queue (drained to exhaustion first, completing the macrostep) from the *external* event queue (one event dequeued per macrostep) precisely so that machine-generated events are not stuck behind external traffic — see the `mainEventLoop` algorithm and the "internal event"/"external event" definitions in the Informal Semantics appendix of <https://www.w3.org/TR/scxml/>. `AfterEvent` here goes to the single, external-style queue.

`task_manager.py:7` acknowledges the design in a comment — background tasks "are typically created for background operations like `after` timers and `invoke`" — but the manager only handles lifecycle/cancellation, not scheduling or priority.

`SyncInterpreter` uses `threading.Timer` (see LC-38), which avoids the loop but introduces unlocked cross-thread context mutation instead — a different defect, not a fix.

## Impact

**General users.** `after` is the documented, obvious way to express every timed concern: retry backoff, request timeout, debounce, watchdog, polling interval. All of them are quiet and correct in development, where the loop is idle and the error is the +6 to +11 ms measured above. All of them silently become hundreds of milliseconds late in production, where the loop is busy — and they degrade *together*, since they share the cause. A timeout that fires 200 ms late is a timeout that no longer bounds anything; a watchdog that fires 2.25 s late under 500 actors is a watchdog that fires long after the condition it guards has caused the damage. Because the error is additive and load-dependent, it cannot be compensated by tuning the nominal delay. And because there is no clock injection (LC-27), it cannot be reproduced in a test — the characteristic is invisible to the test suite by construction, which is presumably how the existing suite passes over it.

**CandleViewer (trading OMS).** CandleViewer is a trading order-management system we are evaluating this library for; almost every timed budget we have is expressed as an `after`:

- **Order chase logic** — a 200 ms `after` re-prices a resting order against the touch. At +210 ms it fires roughly when the next one should have, the order sits stale on a moving book, and we are quoting a price that no longer exists.
- **Stop-loss deadline** — a 2–3 s `after` bounds how long a protective exit may remain unfilled before escalating to a market order. Late by 2.25 s under load, the escalation happens after the adverse move it exists to cap; the loss is realised at the price we were trying to avoid. Note that load and volatility are the same event: the burst of fills that saturates the loop *is* the move.
- **250 ms quote refills, TWAP slice timers, a 10 s WebSocket pong, a 5 s feed watchdog** — all inherit the same error. The 10 s pong is the mildest and still nasty: drifting past the venue's keepalive window drops the WS connection, which drops the feed, during the exact burst that caused the drift.

This is why our adoption rules take every deadline away from the library and give it to an external monotonic scheduler that owns absolute timestamps and sends plain events — an entire component that exists only to work around this, and which forfeits the legibility of having the deadline visible in the machine definition.

## Proposed fix

**Location.** `src/xstate_statemachine/interpreter.py:999-1040` (`_after_timer_task`, `_after_timer`), with support from `task_manager.py`.

Three options, in increasing order of cost, and they compose:

**1. Deliver `AfterEvent` with priority (cheap, fixes half the problem).** A fired timer should not queue behind unprocessed external events. Give the interpreter a small high-priority deque that `_run_event_loop` checks before `_event_queue`, and have `_after_timer_task` push there instead of calling `send()`. This aligns with the SCXML internal/external distinction and removes the second of the two delay sources entirely — including on an idle loop, where it is the only source for a backlogged machine.

**2. Injectable clock / scheduler (the real fix, and the one that makes this testable).**

```python
class Clock(Protocol):
    def now(self) -> float: ...
    def schedule(self, delay_sec: float, fn: Callable[[], None]) -> Handle: ...

Interpreter(machine, clock=my_clock)
```

The default implementation is today's `asyncio.sleep` task, so nothing changes for existing users. A `ThreadedClock` (one `threading.Timer`-style thread that marshals expiry back to the loop via `call_soon_threadsafe`) gives deadlines that do not depend on loop saturation. A `VirtualClock` makes `after` deterministic in tests, which closes LC-27 at the same time and is the single highest-leverage part of this proposal.

**3. Report the drift.** Record `scheduled_for` vs `fired_at` on the `AfterEvent` and expose the delta, so an application can alarm on timer lateness instead of inferring it from symptoms. Trivial to add once (2) exists.

**Backwards compatibility.** All three are additive. (1) changes ordering only for `AfterEvent`s that were previously delivered *behind* external events — which is the bug, and which no documented guarantee covers; it should still be called out in the changelog. (2) defaults to current behaviour. (3) is new data on an existing object.

**If none of this is done,** the minimum acceptable outcome is documentation: a "Timers and the event loop" section on the delayed-transitions page stating that `after` shares the event loop with event processing, that the observed error is additive and load-dependent (with the numbers above), that it does not scale down with the nominal delay, and that sub-100 ms deadlines under load require an external scheduler. This is the largest undocumented production characteristic we found in the library, and users are building stop-losses on it.

## Acceptance criteria

- [ ] `AfterEvent` delivery is not queued behind pending external events; a machine with a deep inbox still honours a due `after`.
- [ ] An injectable clock/scheduler is accepted by `Interpreter` (and `SyncInterpreter`), defaulting to current behaviour.
- [ ] A virtual clock implementation is shipped, so `after` can be tested deterministically without wall-clock sleeps.
- [ ] Under 100 busy interpreters, a 10 ms `after` fires within a documented, tested bound (the repro's +50 ms tolerance is a reasonable target; the bound matters less than it being *stated and enforced*).
- [ ] `repro/LC-26_after_timer_starvation.py` exits `0`.
- [ ] Tests added under `tests/`:
  - `tests/test_timer_scheduling.py::test_after_event_is_not_queued_behind_external_events`
  - `tests/test_timer_scheduling.py::test_after_fires_within_bound_under_loop_load`
  - `tests/test_timer_scheduling.py::test_virtual_clock_drives_after_deterministically`
  - `tests/test_timer_scheduling.py::test_custom_clock_is_used_for_after_delays`
  - `tests/test_timer_scheduling.py::test_default_clock_preserves_existing_behaviour`
  - `tests/test_timer_scheduling.py::test_timer_drift_is_reported_on_after_event`
- [ ] Docs: a "Timers and the event loop" section on the delayed-transitions page with the measured characteristic and the external-scheduler guidance.

## Related

These are sibling reports from the same evaluation; each is self-contained and can be read independently.

- **LC-27** — no clock injection / no virtual time; the proposed `Clock` protocol closes both and is why they should probably be fixed together.
- **LC-20** — restore does not resume pending `after` timers; the same subsystem, the same "timers are second-class" theme.
- **LC-38** — `SyncInterpreter`'s `threading.Timer` avoids the loop but mutates context without a lock.
- **LC-39 / LC-40 / LC-41** — throughput is a fixed global budget (~8.8k ev/s measured on this machine) and the event queue is unbounded; the load side of the same coin, since it determines how starved the loop gets.

## Verification

- Verified: 2026-09-15
- Python: 3.13.7, Windows-11-10.0.26200-SP0
- Library commit: `42612cf`, version 0.7.0 (editable install)
- Command: `python repro/LC-26_after_timer_starvation.py`
- Exit code: `1` (fails against the library as shipped)
- Root-cause lines re-checked against source: `interpreter.py:999` (`_after_timer_task`), `:1011` (`await asyncio.sleep(delay_sec)`), `:1027`/`:1038` (`_after_timer` → `asyncio.create_task`), `:375` (`send()` → `_event_queue.put`), `:427` (`_run_event_loop` → `_event_queue.get`), `task_manager.py:1-14` (module comment). All confirmed.
- Expected-behaviour claims re-checked against <https://stately.ai/docs/delayed-transitions>, XState `packages/core/src/system.ts` (`Clock` interface, `createSystem({ clock })`, `_scheduledEvents`), and <https://www.w3.org/TR/scxml/> (internal vs external event queue, `mainEventLoop`). Corrected: the previously quoted delayed-transitions sentence was a paraphrase, and the SCXML citation pointed at the wrong section number.
- Note: timing figures are measurement-dependent; the Observed block records one real run and the surrounding text states the run-to-run range.
