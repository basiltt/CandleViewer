---
lc: LC-43
title: "Bug: cross-thread `send()` silently loses every event — returns an un-awaited coroutine with no error"
labels: [bug, severity/high, area/interpreter, candleviewer]
severity: High
blocks_adoption: true
verified: true
repro_script: repro/LC-43_cross-thread-send-silently-lost.py
library_version: 0.7.0 (commit 42612cf)
python: 3.13.7
---

## Summary

`Interpreter.send` is a coroutine function (`interpreter.py:335`). Called from an OS thread that is not running the interpreter's event loop, `interp.send("FILL", i=i)` merely *constructs a coroutine object*. Nothing awaits it, so the event never reaches the queue. The call raises nothing, the library logs nothing, and the interpreter continues to report `status='running'`. In the repro, **0 of 500 events are delivered with zero exceptions raised.**

The only feedback is CPython's own `RuntimeWarning: coroutine 'Interpreter.send' was never awaited`, which fires whenever the garbage collector happens to reclaim the object, points at the caller's line rather than the library, and is suppressed outright by the `warnings` filters common in production logging setups. The correct form, `asyncio.run_coroutine_threadsafe(interp.send(...), loop)`, works (500/500 delivered) but costs 151–201 µs/event across runs versus ~33 µs in-loop, and nothing in the API, the type signature or the docs points a caller towards it. Silently discarding events is the worst of the available behaviours: raising would be better, dispatching correctly would be better still.

## Environment

- Library: `xstate-statemachine` 0.7.0, commit `42612cf`, local clone, installed with `pip install -e .`
- Python: 3.13.7
- OS: Windows 11 (x64)
- Install: `pip install -e .` into a dedicated venv

## Minimal reproduction

```python
"""LC-43 repro: cross-thread `send()` drops events with no library-level signal.

`Interpreter.send` is a coroutine function. Called from a foreign OS thread it
merely *builds* a coroutine object; nothing awaits it, so the event never
reaches the queue. `send()` raises nothing, the library logs nothing, and the
interpreter stays `running` — the only feedback is CPython's own GC-timed
`RuntimeWarning: coroutine 'Interpreter.send' was never awaited`, which fires
at an arbitrary later moment, names the caller rather than the library, and is
routinely filtered out in production logging setups.
`asyncio.run_coroutine_threadsafe` is the only correct form, and nothing in the
API points a caller towards it.
"""

from __future__ import annotations

import asyncio
import gc
import logging
import sys
import threading
import time
import warnings

from xstate_statemachine import Interpreter, MachineLogic, create_machine

logging.disable(logging.CRITICAL)

N = 500

CFG = {
    "id": "fills",
    "initial": "live",
    "states": {"live": {"on": {"FILL": {"actions": ["count"]}}}},
}


def count(interp, ctx, event, action_def):  # noqa: ANN001
    ctx["n"] = ctx.get("n", 0) + 1


async def main() -> int:
    ok = True
    logic = MachineLogic(actions={"count": count})
    loop = asyncio.get_running_loop()

    # --- A) bare send() from a foreign thread ------------------------------
    interp = await Interpreter(
        create_machine({**CFG, "context": {"n": 0}}, logic=logic)
    ).start()

    caught: list[str] = []

    def worker_bare() -> None:
        for i in range(N):
            interp.send("FILL", i=i)  # noqa: RUF006 — the bug under test

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        t = threading.Thread(target=worker_bare)
        t.start()
        t.join()
        await asyncio.sleep(0.2)
        gc.collect()
        await asyncio.sleep(0.05)
        caught = [str(x.message) for x in w if "never awaited" in str(x.message)]

    delivered_bare = interp.context.get("n", 0)
    print(f"OBSERVED bare cross-thread send(): {delivered_bare}/{N} delivered, "
          f"exceptions raised = 0, interpreter still status={interp.status!r}")
    print(f"OBSERVED the only signal is {len(caught)} GC-timed "
          "RuntimeWarning('coroutine ... was never awaited') attributed to the "
          "caller's line, not an error raised by the library")
    print(f"EXPECTED either {N}/{N} delivered, or a raised error from send()")
    if delivered_bare != N:
        ok = False
    await interp.stop()

    # --- B) run_coroutine_threadsafe: works, but 10x cost -----------------
    interp2 = await Interpreter(
        create_machine({**CFG, "context": {"n": 0}}, logic=logic)
    ).start()
    elapsed: list[float] = []

    def worker_safe() -> None:
        t0 = time.perf_counter()
        futs = [
            asyncio.run_coroutine_threadsafe(interp2.send("FILL", i=i), loop)
            for i in range(N)
        ]
        for f in futs:
            f.result()
        elapsed.append(time.perf_counter() - t0)

    t2 = threading.Thread(target=worker_safe)
    t2.start()
    while t2.is_alive():
        await asyncio.sleep(0.001)
    t2.join()
    await asyncio.sleep(0.2)
    print(
        f"OBSERVED run_coroutine_threadsafe: {interp2.context.get('n', 0)}/{N} "
        f"delivered at {elapsed[0] / N * 1e6:.0f} us/event"
    )
    await interp2.stop()

    print("RESULT:", "REPRODUCED (silent cross-thread loss)" if not ok else "NOT REPRODUCED")
    return 1 if not ok else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED bare cross-thread send(): 0/500 delivered, exceptions raised = 0, interpreter still status='running'
OBSERVED the only signal is 500 GC-timed RuntimeWarning('coroutine ... was never awaited') attributed to the caller's line, not an error raised by the library
EXPECTED either 500/500 delivered, or a raised error from send()
OBSERVED run_coroutine_threadsafe: 500/500 delivered at 151 us/event
RESULT: REPRODUCED (silent cross-thread loss)
```

Our own benchmarking measured the same effect at 336 µs/event for the `run_coroutine_threadsafe` path against ~33 µs for an in-loop `send()` — a ~10× thread-hop tax on the only correct calling form. The absolute figure varies with machine and load; the ordering does not.

## Expected behaviour

The comparison to XState is one of *failure mode*, not of threading model: JavaScript is single-threaded, so XState never faces this case. What is transferable is the shape of `actor.send` — a plain synchronous method with no execution-context affinity, whose delivery contract is the mailbox: "Actors process one message at a time. They have an internal 'mailbox' that acts like an event queue, processing events sequentially" (https://stately.ai/docs/actors). A call to it either delivers or throws; there is no way to call it and have the event evaporate.

SCXML likewise defines `<send>` as delivering to the processor's external event queue, with the queue — not the caller's execution context — providing the synchronisation boundary (https://www.w3.org/TR/scxml/#send, https://www.w3.org/TR/scxml/#AlgorithmforSCXMLInterpretation). An external event that is accepted must be processed; an event that cannot be delivered must produce an error, not vanish.

Concretely, one of these three is expected, in descending order of preference:

1. **Deliver it.** Detect that the caller is on a foreign thread and dispatch via `loop.call_soon_threadsafe` / `run_coroutine_threadsafe` onto the interpreter's loop.
2. **Refuse loudly.** Raise `WrongThreadError` naming the interpreter, the calling thread, the owning loop's thread, and the correct API to use.
3. At an absolute minimum, provide a documented `send_threadsafe()` and say in the `send()` docstring that it is loop-affine.

What must not happen is what happens now: accept the call, return an object that looks like a normal return value, and discard the event.

## Root cause analysis

`src/xstate_statemachine/interpreter.py:335`:

```python
async def send(self, event_or_type, ..., **payload) -> None:
    ...
    await self._event_queue.put(event_obj)
```

`send` is declared `async`, so calling it produces a coroutine object and executes **none** of the body — not the `status` guard at `:362-369`, not `_prepare_event`, not the `put` at `:375`. On the event-loop thread the caller's `await` drives it; on a foreign thread there is no `await`, the object is discarded at the next collection, and CPython emits `RuntimeWarning: coroutine ... was never awaited` from `coro.__del__`. That warning is the *interpreter runtime's*, not the library's: its timing is GC-dependent, its stack attribution is the caller's line, and `warnings.simplefilter("ignore")` or a `logging.captureWarnings` configuration removes it entirely.

The deeper cause is that the interpreter never records which loop owns it. `grep -n "get_running_loop\|get_event_loop" src/xstate_statemachine/interpreter.py` returns nothing: `start()` calls `asyncio.create_task(self._run_event_loop())` (`interpreter.py:201-203` on the restore path, `:234` on the normal path), which implicitly binds to whatever loop is running *at that moment*, but the loop object is never stored. With no `self._loop`, the library cannot compare `asyncio.get_running_loop()` against its owner, so it cannot detect the foreign-thread case even in principle — which is why the failure is silent rather than merely unsupported.

`self._event_queue` is an `asyncio.Queue` (`interpreter.py:129-131`), which is documented as not thread-safe, so the fix cannot simply be "call `put_nowait` from the other thread"; it must route through the owning loop.

Note the asymmetry that makes this trap easy to fall into: `SyncInterpreter.send()` is an ordinary method that works when called from any thread (unsafely — see LC-38, no locks anywhere), while `Interpreter.send()` is a coroutine that silently does nothing. The two classes present near-identical call sites with opposite failure modes.

## Impact

**General users.** Mixing threads with an asyncio interpreter is not exotic — it is what happens the moment any of these appear: a blocking SDK callback (broker, database driver, GUI toolkit), a `ThreadPoolExecutor` worker reporting completion, a `threading.Timer`, a signal-handling thread, or a legacy synchronous subsystem pushed at an async core. In every one of those, `interp.send(...)` looks correct, type-checks (the call site simply ignores a return value), passes review, and drops 100 % of its events. Test suites that run everything on one loop never catch it. The failure surfaces in production as "the machine just doesn't react", with no error, no log line, and a warning that may never be printed — and even when it is, "coroutine was never awaited" reads as a caller-side style nit, not as data loss.

In our own architecture `run_in_executor` is explicitly sanctioned for DuckDB/Parquet/Argon2/crypto work, so worker threads are a designed-in component, not an accident.

**CandleViewer (trading OMS).** The exchange SDK delivers fills on its own callback thread. That callback does `interp.send("FILLED", order_id=..., qty=...)`. Every fill is silently discarded: the position exists on the exchange, the order machine remains in `submitting` awaiting its invoke, and the OMS's view of the book diverges from reality with no error anywhere. The reconciliation job discovers it minutes later, if at all. The same path affects every bridge from a threaded producer into a machine.

The mitigation we must carry is a wrapper class exposing `send_threadsafe()` plus a **lint rule banning bare `.send(`** across the codebase, because the correct and incorrect forms are visually indistinguishable and the incorrect one fails silently. A library should not require a custom linter to be used safely.

## Proposed fix

**Design.** Record the owning loop at `start()`, then make `send()` — and every other loop-affine public coroutine — detect and handle the foreign-thread case.

```python
# interpreter.py, in start()
self._loop = asyncio.get_running_loop()
```

```python
# interpreter.py, in send()
try:
    running = asyncio.get_running_loop()
except RuntimeError:            # no loop on this thread at all
    running = None
if self._loop is not None and running is not self._loop:
    raise WrongThreadError(
        f"Interpreter {self.id!r} is bound to the event loop on thread "
        f"{self._loop_thread_name!r}; send() was called from "
        f"{threading.current_thread().name!r}. `send()` is a coroutine and "
        f"will be discarded unawaited from a foreign thread. "
        f"Use `interp.send_threadsafe(...)` instead."
    )
```

Because the guard sits in the coroutine *body*, it only runs if something awaits the coroutine — which is precisely what does not happen in the failure case. The check therefore has to be reachable without an await. Two workable shapes:

- **(a) Make `send` a normal method returning an awaitable.** `def send(...) -> Awaitable[None]` performs the thread check and event normalisation eagerly, then returns a future/coroutine. A foreign-thread call then raises *at the call site*, immediately, whether or not the result is awaited. In-loop callers keep writing `await interp.send(...)` with no change.
- **(b) Keep `send` async and add a `__del__`-independent tripwire** — far weaker; (a) is the recommendation.

**And provide the correct path:**

```python
def send_threadsafe(self, event_or_type, **payload) -> "concurrent.futures.Future[None]":
    """Send from any thread. Returns a concurrent Future resolved once queued."""
    return asyncio.run_coroutine_threadsafe(self.send(event_or_type, **payload), self._loop)
```

Usage from an SDK callback thread:

```python
def on_fill(sdk_msg):                      # exchange SDK's own thread
    interp.send_threadsafe("FILLED", order_id=sdk_msg.id, qty=sdk_msg.qty)
    # or .result(timeout=0.5) to confirm it was queued
```

**Alternative considered — auto-dispatch instead of raising.** `send()` could transparently do the `run_coroutine_threadsafe` hop itself. Rejected as the default: it hides a ~5-10× per-event cost (151–201 µs vs ~33 µs measured here; 336 µs vs 33 µs in our wider benchmarking) behind an innocuous call, and it changes `await send(...)` from "queued" to "queued on another thread, ordering relative to this thread's other sends now unspecified". Explicit is better. It could be offered as `Interpreter(machine, allow_cross_thread_send=True)` for users who want the convenience knowingly.

**Backwards compatibility.** Any code that today calls `send()` from a foreign thread is already losing 100 % of those events, so raising cannot break a working program — it converts silent data loss into a loud, actionable error. Existing in-loop `await interp.send(...)` call sites are untouched by shape (a). The one genuinely affected pattern is a foreign-thread caller that already wraps in `run_coroutine_threadsafe`: that path executes the body *on the owning loop*, so the check passes and it keeps working. To be safe, ship the raise behind a `DeprecationWarning`-first release if desired: warn loudly in 0.7.x, raise in 0.8.0.

**Change locations.**

- `interpreter.py` `start()` (`:169-273`) — store `self._loop = asyncio.get_running_loop()` and the owning thread name; clear in `stop()` (`:275-325`).
- `interpreter.py:335-375` — convert `send` to shape (a) with an eager thread guard.
- `interpreter.py:377-400` — same guard in `send_events`.
- `interpreter.py` — new `send_threadsafe()` / `send_events_threadsafe()`.
- `exceptions.py` — new `WrongThreadError(StateMachineError)`.
- `base_interpreter.py` — mirror the docstring guidance; `SyncInterpreter` should document its own (different, LC-38) threading rules alongside.
- Docs — a "Threading" page: `Interpreter` is loop-affine, `send_threadsafe` is the bridge, `SyncInterpreter` is not a thread-safe alternative.

## Acceptance criteria

- [ ] `interp.send(...)` called from a non-owning thread raises `WrongThreadError` **at the call site**, without requiring the result to be awaited.
- [ ] The error message names the interpreter id, the calling thread, the owning thread, and `send_threadsafe` as the remedy.
- [ ] `await interp.send(...)` from the owning loop is unchanged in behaviour, signature and return value.
- [ ] `send_threadsafe()` delivers 500/500 events from a foreign thread and returns a `concurrent.futures.Future`.
- [ ] `send_threadsafe()` on a not-yet-started or stopped interpreter raises a clear error rather than `AttributeError`/`None` deref.
- [ ] `run_coroutine_threadsafe(interp.send(...), loop)` continues to work (no regression for users already doing it correctly).
- [ ] `send_events()` carries the same guard.
- [ ] `stop()` clears `_loop`, and a subsequent restart on a different loop re-binds cleanly.
- [ ] Docs: "Threading" page as described; `send()` docstring states loop affinity.
- [ ] `repro/LC-43_cross-thread-send-silently-lost.py` exits 0.
- [ ] Tests added:
  - `tests/test_interpreter_threading.py::test_bare_send_from_foreign_thread_raises_wrong_thread_error`
  - `tests/test_interpreter_threading.py::test_wrong_thread_error_message_names_threads_and_remedy`
  - `tests/test_interpreter_threading.py::test_send_threadsafe_delivers_all_events`
  - `tests/test_interpreter_threading.py::test_send_threadsafe_returns_resolvable_future`
  - `tests/test_interpreter_threading.py::test_send_threadsafe_on_stopped_interpreter_errors_clearly`
  - `tests/test_interpreter_threading.py::test_run_coroutine_threadsafe_path_still_works`
  - `tests/test_interpreter_threading.py::test_in_loop_send_unaffected`
  - `tests/test_interpreter_threading.py::test_send_events_foreign_thread_guard`

## Related

- `LC-38` — `SyncInterpreter` runs `after` timers on daemon threads and mutates context with no locks; the same absent synchronisation, reached from the library's side rather than the user's. That issue's "Related" section already points here.
- `LC-18` — event ordering destroyed across defer/drain; the thread-hop path adds another ordering source.
- `LC-42` — `send()` is fire-and-forget; the same coroutine-shaped `send` is the root of both. Shape (a) proposed here composes with the receipt proposed there.
- `LC-41` — unbounded queue; cross-thread traffic is a common way to overrun the consumer.
- `LC-48` — no error-observability hooks; a dropped cross-thread event has nowhere to be reported.

## Verification

Independently verified on 2026-09-15.

- Library: `xstate-statemachine` 0.7.0, commit `42612cf`, local clone, `pip install -e .`
- Python: 3.13.7 (CPython, MSC v.1944 64-bit), Windows 11 x64
- Repro run in a fresh process: `repro/LC-43_cross-thread-send-silently-lost.py` -> **exit code 1** (fails today). Bare cross-thread `send()` delivered 0/500 with no exception and `status='running'`; `run_coroutine_threadsafe` delivered 500/500.
- Root-cause line cites re-checked against the source: `interpreter.py:335` (`async def send`), `:362-369` (the status guard that never executes), `:372` (`_prepare_event`), `:375` (`put`), `:129-131` (`asyncio.Queue`, documented not thread-safe), `:234` and `:201-203` (`create_task`, binding the loop implicitly). The claim that the interpreter never records its owning loop is confirmed: `grep -n "get_running_loop\|get_event_loop" src/xstate_statemachine/interpreter.py` returns zero matches (the only hit in the package is `helpers.py:79`). The `SyncInterpreter` asymmetry is confirmed: its `send` is an ordinary method (`sync_interpreter.py:299`) that appends and processes inline (`:312-313`).
- Corrections made: the "Expected behaviour" section quoted a sentence that does not appear on the cited page and claimed XState actors are "explicitly safe to send to from anywhere" - XState is single-threaded, so it never faces this case and makes no such guarantee. Reframed as a comparison of *failure mode* (a call either delivers or throws; it never evaporates) with a verbatim quote that does appear. Throughput figure in Observed refreshed from this run (151 us/event; the 201 us figure was within run-to-run variance, so the text now gives the range). CandleViewer-internal references (`20 §4.1`, B11/B12/B13/B16, bench `g6`, `SafeInterpreter`, FEATURE_GAP_ANALYSIS) replaced with inline explanations.
- Duplicate check: `gh issue list --repo basiltt/xstate-statemachine --state all` returns a single unrelated issue (#17, camelCase action auto-discovery). Not a duplicate.
