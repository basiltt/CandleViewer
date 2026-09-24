---
r5: R5-16
title: "Bug: send_threadsafe has no usable backpressure signal on the calling thread; overflow is evaluated after the call returns"
labels: [bug, severity/medium, area/interpreter]
severity: Medium
repro_script: repro/R5-16_send-threadsafe-no-backpressure.py
commit: 3ed3099
python: 3.13.7
verified: true
---

## Summary

`send_threadsafe` is the documented cross-thread ingress API
(`interp.send_threadsafe("X")`, called fire-and-forget from a producer
thread), and `max_queue_size` / `overflow_policy` are documented as the
bound on the interpreter's inbox. But `send_threadsafe` schedules its
`_enqueue()` call onto the event loop and returns a
`concurrent.futures.Future` immediately; the bound is therefore checked on
the LOOP, after the calling thread has already returned. Under
`OverflowPolicy.RAISE`, the resulting `QueueOverflowError` is attached to
that already-returned future, which the documented usage pattern never
reads — so a producer thread that floods an interpreter gets no signal at
all that any of its events were refused.

## Environment

- Commit: `3ed3099` (`main`, unreleased 0.8.1; `__version__` still reports
  `0.8.0`, so this build is identified by commit).
- Python: CPython 3.13.7
- OS: Windows 11 Pro 10.0.26200
- Editable install of the repo into a local venv; no library source
  modified.

## Minimal reproduction

```python
"""R5-16 repro: `send_threadsafe` has no usable backpressure signal on the
calling thread.

`send_threadsafe` schedules `_enqueue()` onto the event loop
(`interpreter.py`), so the bounded-queue overflow check runs on the LOOP,
after the calling thread has already returned. Under `OverflowPolicy.RAISE`
the resulting `QueueOverflowError` is attached to the returned
`concurrent.futures.Future` -- which the documented fire-and-forget usage
(`interp.send_threadsafe("X")`, result never read) never inspects. The
producing thread is told nothing.

Exits 1 while the defect is present, 0 once fixed.
Stdlib + xstate_statemachine only.
"""
from __future__ import annotations

import asyncio
import sys
import threading

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.models import OverflowPolicy

CFG = {
    "id": "ctr",
    "initial": "a",
    "context": {"n": 0},
    "states": {"a": {"on": {"PING": {"actions": ["bump"]}}}},
}


def bump(interpreter, ctx, event, action_def):
    ctx["n"] += 1


async def main() -> int:
    logic = MachineLogic(actions={"bump": bump})
    interp = Interpreter(
        create_machine(CFG, logic=logic),
        max_queue_size=100,
        overflow_policy=OverflowPolicy.RAISE,
    )
    await interp.start()

    n_threads = 16
    sent = 0
    raised_on_thread = 0
    futures = []
    lock = threading.Lock()

    def producer():
        nonlocal sent, raised_on_thread
        for _ in range(200):
            try:
                f = interp.send_threadsafe("PING")
                with lock:
                    sent += 1
                    futures.append(f)
            except Exception:  # noqa: BLE001
                with lock:
                    raised_on_thread += 1

    threads = [threading.Thread(target=producer) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    await asyncio.sleep(0.5)

    overflow_on_future = sum(
        1 for f in futures if f.done() and f.exception() is not None
    )

    print("OBSERVED:")
    print(f"  calls_returned_without_raising_on_calling_thread = {sent}")
    print(f"  raised_on_calling_thread                         = {raised_on_thread}")
    print(f"  QueueOverflowError_landed_on_unread_future        = {overflow_on_future}")

    print("EXPECTED:")
    print("  overflow under RAISE is signalled to the CALLING thread synchronously,")
    print("  e.g. send_threadsafe raises QueueOverflowError before returning, or the")
    print("  bound is checked before scheduling onto the loop")

    failed = raised_on_thread == 0 and overflow_on_future > 0
    print("RESULT:", "FAIL - no calling-thread backpressure signal" if failed else "PASS")
    await interp.stop(drain=True, timeout=30)
    return 1 if failed else 0


sys.exit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED:
  calls_returned_without_raising_on_calling_thread = 3200
  raised_on_calling_thread                         = 0
  QueueOverflowError_landed_on_unread_future        = 3100
EXPECTED:
  overflow under RAISE is signalled to the CALLING thread synchronously,
  e.g. send_threadsafe raises QueueOverflowError before returning, or the
  bound is checked before scheduling onto the loop
RESULT: FAIL - no calling-thread backpressure signal
```

The register's own battle script (`concurrency/b3_threadsafe_backpressure.py`,
re-run fresh, 32 threads/cap 100) confirms the pattern at larger scale: under
`RAISE`, 6400 `send_threadsafe` calls "returned without raising on the
calling thread"; 5196 of the matching futures resolved with
`QueueOverflowError`; `raised_on_calling_thread = 0`. Under `DROP_NEWEST` the
drop is correctly hooked (`on_event_dropped` fired 5629 times) — only the
`RAISE` policy's signal is unreachable from the calling thread.

## Expected behaviour

The library documents `overflow_policy=OverflowPolicy.RAISE` as a way for a
bounded interpreter to refuse further events under load — the natural
reading (and the behaviour of the synchronous `send()` path, which
evaluates the bound before returning) is that a caller who chooses `RAISE`
learns synchronously, at the call site, that its event was refused, so it
can retry, drop, or apply its own backpressure. A cross-thread producer
using the documented fire-and-forget `send_threadsafe(...)` call pattern
gets none of that: the exception exists but is unreachable without
capturing and blocking on every returned future, which defeats the purpose
of a non-blocking threadsafe API.

## Root cause analysis

`interpreter.py:1002-1045` (`send_threadsafe`): after the calling-thread
`_prepare_event`/`_check_strict` guards, the enqueue itself is wrapped in an
inner `async def _deliver(): self._enqueue(event_obj)` and scheduled via
`asyncio.run_coroutine_threadsafe(_deliver(), self._loop)` (line 1045),
returning the resulting `concurrent.futures.Future` immediately — the
calling thread never blocks on it. The bound check (`max_queue_size` /
`overflow_policy`) lives inside `_enqueue()` (`interpreter.py:966-1000`),
which only runs later, on the loop thread. Under `OverflowPolicy.RAISE` that
raises `QueueOverflowError` *inside the scheduled coroutine*
(`interpreter.py:995`), which `run_coroutine_threadsafe` attaches to the
future it already returned — exactly the object the documented one-line
call-and-forget usage discards.

## Impact

General: any application relying on `OverflowPolicy.RAISE` from a
non-asyncio producer thread (the primary reason to call `send_threadsafe`
at all) silently loses its only backpressure signal; the queue still
protects the interpreter from unbounded growth, but the producer has no way
to know it needs to slow down or that data was dropped.

Order-management scenario: a market-data or fill-notification thread that
feeds the OMS state machine via `send_threadsafe` under load has no way to
detect that its events are being refused — the 6400-call, cap-100 backlog
in the battle script shows the vast majority of calls "succeed" from the
producer's point of view while the corresponding fill/tick events are
silently discarded server-side.

## Proposed fix

Give `send_threadsafe` a synchronous backpressure check before scheduling:
sample `queue_depth` against `max_queue_size` on the calling thread (best-
effort, accepting the race against concurrent producers) and raise
`QueueOverflowError` immediately under `RAISE` if already at/over capacity,
the same way `send()`'s synchronous path does. For the residual race window
(depth checked but exceeded by the time `_enqueue()` actually runs), document
that the authoritative check still happens on the loop and that a caller
wanting a guarantee must inspect the returned future — but the common case
(steady overload) is now caught synchronously. Alternatively/additionally,
provide a `send_threadsafe(..., block=True, timeout=...)` variant that waits
on the future before returning, for callers who want the guarantee without
manually managing futures.

Compatibility: additive — the default synchronous pre-check only raises in
cases that would already fail asynchronously; callers not handling the
exception today get an earlier, louder failure instead of a silent drop, and
should be warned of this in the changelog since it changes when the
exception is thrown (though not whether it is).

## Acceptance criteria

- [ ] `repro/R5-16_send-threadsafe-no-backpressure.py` exits `0`.
- [ ] `tests/test_interpreter_threadsafe.py::test_send_threadsafe_raises_on_calling_thread_when_full`
      — under `RAISE` and a saturated bounded queue, the exception is
      raised at the `send_threadsafe(...)` call site itself.
- [ ] `tests/test_interpreter_threadsafe.py::test_send_threadsafe_drop_newest_unchanged`
      — regression guard: `DROP_NEWEST` behaviour (hooked drop, no
      exception) is unaffected.
- [ ] `tests/test_interpreter_threadsafe.py::test_send_threadsafe_future_still_resolves_with_error`
      — the returned future continues to carry the exception for callers
      who do inspect it.
- [ ] Changelog entry documenting the new synchronous-raise timing for
      `OverflowPolicy.RAISE` via `send_threadsafe`.

## Related

- Register id: `D-concurrency-6` (§3, `33-r5-findings-register.md`).
- Evidence: `battle-3ed3099/concurrency/b3_threadsafe_backpressure.py`.

## Verification

- Date: 2026-09-19
- Python: CPython 3.13.7 (`.venv-main`)
- Commit: `3ed3099` (`main`, unreleased 0.8.1)
- `repro/R5-16_send-threadsafe-no-backpressure.py` re-run fresh: exit `1`
  (FAIL — defect still present); observed `raised_on_calling_thread = 0`,
  `QueueOverflowError_landed_on_unread_future = 3100`, matching the recorded
  behaviour.
- Root cause re-checked against source and citation corrected: the original
  draft's `interpreter.py:911-914` citation was wrong (that range is inside
  `_refuse_if_not_running`, unrelated). Confirmed instead:
  `interpreter.py:1002-1045` (`send_threadsafe`, ending in
  `asyncio.run_coroutine_threadsafe(_deliver(), self._loop)` at line 1045,
  returning the future immediately); `interpreter.py:966-1000` (`_enqueue`,
  the synchronous bound check `if self._inbox_is_full(): ... raise
  QueueOverflowError(...)` at line 995) — confirms the overflow check runs
  inside the coroutine scheduled onto the loop, not on the calling thread.
  The finding file has been corrected in place to cite the verified lines.
- Duplicate check: `gh issue list -R basiltt/xstate-statemachine --state all
  --limit 150 --search "send_threadsafe backpressure"` — no matches beyond
  the tracking issue `#26`; not a duplicate of any existing issue.
- `verified: true` set in frontmatter.

