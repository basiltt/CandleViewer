---
r5: R5-07
title: "Perf: #116 regression — a plain-`def` invoked service now runs inline on the async run loop, stalling every timer, actor and inbound send for its full duration"
labels: [bug, performance, severity/high, area/interpreter, area/actors]
severity: High
repro_script: repro/R5-07_plain_def_service_blocks_loop.py
commit: 3ed3099
python: 3.13.7
verified: true
---

## Summary

`#116` fixed a genuine ordering divergence between the sync and async engines
by running a non-coroutine invoked service **inline**, inside the macrostep
that enters the invoking state, with its `done.invoke` delivered through the
priority lane. The ordering half of that fix is correct and worth keeping. The
execution half is not: a plain `def` service is arbitrary blocking user code,
and running it inline occupies the asyncio event loop for its entire
wall-clock duration. An 0.8 s service blocks `await start()` for 0.800 s and a
concurrently running 10 ms ticker advances **zero** times — no timer, no child
actor, no inbound `send`, and no other coroutine in the application is
serviced for the duration. This is a regression of intent introduced by #116:
the previous task-based path did not block the loop, and nothing in #116's
stated goal (ordering) requires that it do so.

## Environment

- Commit: `3ed3099` (`main`, "Merge pull request #139 from fix/0.8.1-round4"),
  unreleased 0.8.1 (`__version__` still reports `0.8.0`; keyed on the commit)
- Python: 3.13.7 (CPython, 64-bit)
- OS: Windows 11 Pro (10.0.26200)
- Install: editable (`pip install -e .`) into a project venv
- Found by our adoption audit (#26), round 5.

## Minimal reproduction

```python
# -*- coding: utf-8 -*-
"""R5-07: a plain-`def` invoked service runs INLINE on the async run loop,
stalling every timer, actor and inbound send for its full duration (#116).

#116 made a non-coroutine service run inline, inside the macrostep that
enters the invoking state, to fix an ordering divergence between the sync and
async engines. The side effect is that `await Interpreter(...).start()` now
blocks the event loop for the whole wall-clock duration of the service: a
concurrent 10 ms ticker gets ZERO iterations while an 0.8 s service runs.

Standalone: stdlib + xstate_statemachine only.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import warnings

warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)

from xstate_statemachine import Interpreter, MachineLogic, create_machine

SERVICE_SECONDS = 0.8
CFG = {
    "id": "s",
    "initial": "w",
    "states": {
        "w": {"invoke": {"id": "svc", "src": "slow", "onDone": "d"}},
        "d": {},
    },
}


def slow(interp, ctx, event):  # noqa: ANN001 -- a plain, blocking `def` service
    time.sleep(SERVICE_SECONDS)
    return 1


async def main() -> int:
    ticks = {"n": 0}

    async def ticker() -> None:
        while True:
            ticks["n"] += 1
            await asyncio.sleep(0.01)

    task = asyncio.ensure_future(ticker())
    await asyncio.sleep(0.05)  # prove the ticker is alive and scheduled
    baseline = ticks["n"]

    machine = create_machine(
        json.loads(json.dumps(CFG)), logic=MachineLogic(services={"slow": slow})
    )
    started = time.monotonic()
    interp = await Interpreter(machine).start()
    blocked = time.monotonic() - started
    during = ticks["n"] - baseline

    task.cancel()
    await interp.stop()

    print(f"  ticker iterations in the 50 ms BEFORE start(): {baseline}")
    print(f"  await start() blocked for               : {blocked:.3f} s")
    print(f"  ticker iterations DURING start()        : {during}")
    print()
    print(f"OBSERVED: an 0.8 s plain-`def` service blocks `await start()` for "
          f"{blocked:.3f} s and a live 10 ms ticker advances {during} times "
          f"(expected ~{int(SERVICE_SECONDS / 0.01)}). The loop is occupied, so "
          f"no timer, actor or inbound send is serviced for the duration.")
    print("EXPECTED: the async engine never blocks its own event loop. A plain "
          "blocking callable belongs on `run_in_executor`, with its "
          "`done.invoke` delivered through the priority lane so #116's "
          "ordering guarantee is preserved without occupying the loop.")
    blocked_loop = during <= 2
    print("RESULT:", "FAIL" if blocked_loop else "PASS")
    return 1 if blocked_loop else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

## Observed behaviour

```
  ticker iterations in the 50 ms BEFORE start(): 4
  await start() blocked for               : 0.800 s
  ticker iterations DURING start()        : 0

OBSERVED: an 0.8 s plain-`def` service blocks `await start()` for 0.800 s and a live 10 ms ticker advances 0 times (expected ~80). The loop is occupied, so no timer, actor or inbound send is serviced for the duration.
EXPECTED: the async engine never blocks its own event loop. A plain blocking callable belongs on `run_in_executor`, with its `done.invoke` delivered through the priority lane so #116's ordering guarantee is preserved without occupying the loop.
RESULT: FAIL
```

Exit code `1`. The `baseline` line is the control: the ticker is demonstrably
alive and advancing (4 iterations in the preceding 50 ms) right up to the
moment `start()` is called, and then stops dead for the full 0.800 s.

## Expected behaviour

**The asyncio contract the async engine exists to honour.** The Python
documentation is explicit
(https://docs.python.org/3/library/asyncio-dev.html#running-blocking-code):

> Blocking (CPU-bound) code should not be called directly. For example, if a
> function performs a CPU-intensive calculation for 1 second, all concurrent
> asyncio Tasks and IO operations would be delayed by 1 second. An executor
> can be used to run a task in a different thread or even in a different
> process to avoid blocking the OS thread with the event loop.

An event-loop-based interpreter calling arbitrary user code inline on the loop
thread is precisely that anti-pattern. The library's `Interpreter` (as opposed
to `SyncInterpreter`) exists to run concurrently with the rest of an asyncio
application; a mode in which it monopolises the loop for the duration of user
code defeats its purpose, and it does so *silently* — there is no warning, no
documented caveat, and no opt-out.

**XState v5's equivalent.** A `fromCallback` / promise actor never blocks the
scheduler; the actor system is explicitly non-blocking
(https://stately.ai/docs/actors). Ordering between an actor's completion and
queued external events is a *scheduling* property, achieved by where the
completion is enqueued, not by executing the actor body synchronously.

**Compatibility with #116's own goal.** `#116`'s stated invariant, quoted from
`interpreter.py:2110-2121`, is about *delivery order*:

> 🏛️ #116: a PLAIN (non-coroutine) callable runs INLINE, exactly as the sync
> engine runs it -- inside the macrostep that enters the invoking state, with
> its `done.invoke` delivered ahead of any event already waiting in the
> inbox. Wrapping it in a task deferred the call until after the run loop
> yielded, so an external event queued behind the entry (CANCEL) was
> processed BEFORE the completion, and the identical (GO, CANCEL) script
> diverged between engines.

That invariant is about which event is dequeued first. It is fully satisfiable
without executing the service body on the loop thread.

## Root cause analysis

`src/xstate_statemachine/interpreter.py:2110-2125`, in
`_create_invocation_task`:

```python
if _is_plain_sync_callable(service):
    self._invoke_plain_service_inline(invocation, service, owner_id)
    return

async def _invoke_wrapper() -> None:
    await asyncio.sleep(0)
    await self._invoke_service_task(invocation, service)

task = asyncio.create_task(_invoke_wrapper())
self.task_manager.add(owner_id, task)
```

and `_invoke_plain_service_inline` at `interpreter.py:2163-2190`:

```python
        try:
            invoke_event = Event(...)
            produced = service(self, self.context, invoke_event)   # ← on the loop thread
        except Exception as exc:
            self._report_service_failure(invocation, exc)
            return
        if inspect.isawaitable(produced):
            ...  # falls back to a task, correctly
```

`service(...)` is called directly on the calling stack. That stack is the
run-loop task's stack (or, as in the reproducer, `start()`'s own stack during
the initial macrostep), so the call holds the loop thread for its entire
duration. There is no `await` between entering the state and the service
returning, so the loop cannot schedule anything else — timers armed via
`clock.set_timeout`, child-actor run loops, the inbox drain, and every
unrelated coroutine in the host application all stall together.

`_is_plain_sync_callable` (`interpreter.py:155-165`) is careful and correct
about *identifying* a synchronous callable — it looks through `partial`,
callable objects and mock wrappers. The defect is in what is then done with
that classification, not in the classification itself.

Note the asymmetry the current code already contains: if the plain `def`
happens to *return* an awaitable, `_invoke_plain_service_inline` correctly
hands it to a task (`interpreter.py:2179-2211`). So the function already knows
how to route work off the synchronous path; it simply does not do so for the
blocking case, which is the common one.

## Impact

**General users.** The most natural way to write an invoked service — a plain
`def` that does a blocking call (`requests.post`, a DB driver, a file read, a
CPU-bound computation) — now freezes the entire event loop of the host
application for the duration of that call. The `Interpreter` class is chosen
*because* the application is asyncio-based, so the blast radius is not limited
to the machine: every other coroutine in the process stalls. Because the fix
that introduced this was an ordering fix, the change is invisible in the
changelog to anyone reading for performance, and there is no runtime signal
(no warning, no metric) when it happens.

**Concrete order-management scenario.** An order machine invokes a plain
`def place_order(...)` that does a blocking HTTP POST to the venue with a
2 s timeout. Under the previous behaviour that call ran on a task and the loop
kept turning. Now, entering `placing` freezes the loop for up to 2 s. In that
window: the market-data feed coroutine stops draining its socket and falls
behind (or its buffer overflows); every other order machine's `after`-based
exchange-ack timeout stops counting down and then all fire late, in a burst,
against stale state; inbound `CANCEL` events for *other* orders sit unread in
the inbox; and heartbeats to the venue are not sent, risking a
session-level disconnect. One slow venue thus stalls the entire book, and the
stall scales with concurrency — N orders placing simultaneously serialise into
N × 2 s of dead loop, because each inline call also blocks the others.

## Proposed fix

**Design.** Keep #116's ordering guarantee; stop occupying the loop.

1. In `_invoke_plain_service_inline`, replace the direct call with an executor
   hand-off, and deliver the completion through the **same** priority lane the
   function already uses:

   ```python
   fut = self._loop.run_in_executor(
       self._service_executor,          # a lazily-created ThreadPoolExecutor
       functools.partial(service, self, self.context, invoke_event),
   )

   async def _finish() -> None:
       try:
           result = await fut
       except Exception as exc:          # noqa: BLE001 -- user code
           self._report_service_failure(invocation, exc)
           return
       self._deliver_priority(DoneEvent(
           type=f"done.invoke.{invocation.id}", data=result, src=invocation.id,
       ))
       for plugin in self._plugins:
           plugin.on_service_done(self, invocation, result)

   self.task_manager.add(owner_id, self._loop_create_task(_finish()))
   ```

   The ordering property is preserved because `_deliver_priority` — which the
   inline path already calls — puts the completion **ahead of** the inbox
   backlog, which is exactly the mechanism #116 relies on. What changes is
   only *when* the completion is produced, not *where it is inserted*.

2. **Where the ordering guarantee genuinely requires synchrony**, i.e. the
   `(GO, CANCEL)` script in #116's regression test, the completion still wins
   because it enters the priority lane while `CANCEL` is in the normal inbox.
   If a case is found where the sync/async scripts still diverge, the correct
   remedy is for the macrostep to *await* the executor future before
   completing entry — still off the loop thread — rather than to call inline.

3. **Executor lifecycle.** Create the `ThreadPoolExecutor` lazily on first
   plain-service invocation, shut it down in `stop()`/`_teardown()`, and
   expose it as a constructor parameter
   (`Interpreter(machine, service_executor=...)`) so callers can supply a
   shared or bounded pool, or a `ProcessPoolExecutor` for CPU-bound work.
   Default `max_workers` should be explicit rather than inherited from the
   asyncio default, since the number of concurrently invoked services is a
   property of the machine, not of the host.

4. **Interim mitigation if (1) is deferred.** At minimum, emit a
   `RuntimeWarning` the first time a plain `def` service's inline execution
   exceeds a small threshold (say 50 ms), naming the service and pointing at
   `async def` or an executor. Silence is the worst property of this defect;
   a signal makes it diagnosable in production.

**Compatibility.** The observable *ordering* is unchanged (that is the
invariant #116 added tests for, and those tests must keep passing unmodified).
What changes is that user service code now runs on a worker thread, so a
service that mutates `interp.context` directly is no longer implicitly
serialised against the loop. That is a real semantic change and should be
called out in the changelog; the safe migration is that the documented way to
mutate context from a service is its return value flowing into `onDone`
actions, which is unaffected. A `sync_executor=None` escape hatch restoring
the inline behaviour can be offered for anyone who depends on the old
threading model.

**Alternatives considered.**
1. *Revert #116 to the task path.* Rejected: it reintroduces the genuine
   ordering divergence #116 fixed, which is a correctness bug and worse than a
   performance bug.
2. *Document "use `async def`".* Rejected as a primary fix: the sync engine
   accepts plain `def` services and the two engines are advertised as running
   the same machine definitions, so a plain `def` service is a supported
   input, not user error.

## Acceptance criteria

- [ ] `repro/R5-07_plain_def_service_blocks_loop.py` exits `0`.
- [ ] `tests/test_invoke_executor.py::test_plain_def_service_does_not_block_loop`
      — a 0.3 s blocking service with a concurrent 10 ms ticker: the ticker
      advances at least 20 times during the invocation.
- [ ] `tests/test_invoke_executor.py::test_start_returns_promptly_with_slow_plain_service`
      — `await start()` returns in well under the service duration.
- [ ] `tests/test_round4_findings.py`'s existing `#116` ordering test passes
      **unmodified** — the `(GO, CANCEL)` script still produces identical
      transcripts on both engines.
- [ ] `tests/test_invoke_executor.py::test_concurrent_plain_services_run_in_parallel`
      — N machines each invoking a 0.2 s blocking service complete in
      ≈0.2 s total, not N × 0.2 s.
- [ ] `tests/test_invoke_executor.py::test_plain_service_raising_still_reports_error_platform`
      — the failure path (`_report_service_failure`) is unchanged when the
      exception is raised on a worker thread.
- [ ] `tests/test_invoke_executor.py::test_plain_def_returning_awaitable_still_awaited`
      — the existing `inspect.isawaitable` fallback keeps working.
- [ ] `tests/test_invoke_executor.py::test_executor_shutdown_on_stop`
      — no thread leak after `stop()`.
- [ ] `tests/test_invoke_executor.py::test_after_timer_fires_on_time_during_plain_service`
      — an `after` deadline armed before the invocation fires within
      tolerance while the blocking service is running.

## Related

- Round 4: **#116** (`sync_async_invoke_timing_parity` — the commit that
  introduced this; R5-07 ← #116). Its ordering goal is correct and must be
  preserved by the fix, not reverted.
- **R5-04** (Blocker) — the sync engine's nested-invoke livelock: the same
  "invocations execute on the engine's own thread of control" design, taken to
  its non-terminating limit.
- **R5-09** — the settle budget's per-drain reset: another case where a
  scheduling property of the async loop is coupled to something that should be
  per-macrostep.
- Register source id: `J-3` (from `32-r5-diff-review.md`; unmerged 1:1).
- Evidence: `triage-r5/t2_engine.py::J3` (`J3_blocked_s: 0.601`,
  `J3_ticks: 0`) and `probes/main-3ed3099/p2_gate_and_inline.py`
  (`j5_start_blocked_s: 0.803`, `j5_loop_ticks_during_start: 0`).
- Meta: our adoption audit **#26**.

## Verification

- Date: 2026-09-19
- Python: 3.13.7 (`.venv-main`)
- Commit: `3ed3099`
- Ran `repro/R5-07_plain_def_service_blocks_loop.py` in a fresh process: exit
  code `1`, output pasted verbatim above (`0.800 s` blocked, `0` ticks, with
  a live-ticker control of `4` in the preceding 50 ms).
- Root cause confirmed by reading `src/xstate_statemachine/interpreter.py` at
  `:2110-2125` (the `_is_plain_sync_callable` branch) and `:2163-2190`
  (the direct `service(...)` call on the loop thread), plus the
  already-correct awaitable fallback at `:2179-2211`.

## Verification (independent re-run)

- Date: 2026-09-19
- Python: 3.13.7 (`.venv-main`)
- Commit: `3ed3099`
- Fresh-process re-run of `repro/R5-07_plain_def_service_blocks_loop.py`:
  exit code `1`, output byte-identical in shape to the pasted transcript
  above (`0.801 s` blocked, `0` ticker iterations during, `4` in the
  preceding 50 ms control window).
- Root-cause line citations re-checked against source and confirmed exact:
  `interpreter.py:155` (`_is_plain_sync_callable`), `:2123-2124` (the
  `if _is_plain_sync_callable(service): self._invoke_plain_service_inline(...)`
  branch), `:2163` (`_invoke_plain_service_inline` definition, direct
  `service(...)` call on the loop thread).
- Cited asyncio documentation re-verified against the current Python docs
  (`asyncio-dev.html`, "Running Blocking Code"): "Blocking (CPU-bound) code
  should not be called directly... all concurrent asyncio Tasks and IO
  operations would be delayed... An executor can be used to run a task in a
  different thread... to avoid blocking the OS thread with the event loop" —
  matches the quoted text verbatim and supports the proposed
  `run_in_executor` fix.
- Duplicate check: `gh issue list -R basiltt/xstate-statemachine --state all
  --limit 150 --search "plain def service blocks loop"` and `--search "116"`
  return only round-4 `#116` (the parent whose ordering fix introduced this
  performance regression, already cited under Related and in the title) and
  unrelated `#41`. No duplicate.
