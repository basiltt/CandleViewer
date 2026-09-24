---
r7: R7-08
title: "Bug: `_await_settled_for_snapshot` spins `time.sleep` on the event-loop thread, so the mid-step child it waits for can never progress — 501 ms blocked per call, 1502 ms with three children"
labels: [bug, severity/high, area/persistence, area/interpreter]
severity: High
engines: async `Interpreter`
repro_script: repro/R7-08_await_settled_for_snapshot_blocks_loop.py
commit: 221ce7c
python: 3.13.7
verified: true
---

## Summary

`base_interpreter.py:1273-1288` (`_await_settled_for_snapshot`) spins
`time.sleep(0.0005)` — not `await asyncio.sleep` — inside its deadline loop. It
is called from `get_persisted_snapshot()` (`base_interpreter.py:1389-1394`) on
the child branch. On the async engine that runs on the event-loop thread, so
the mid-step child it is waiting for **cannot make progress while it waits**.
The wait is therefore guaranteed to burn its full 0.5 s budget and then return
the unsettled child blob anyway.

```
(b) one mid-step child   : event loop blocked 501 ms, returns unsettled blob
    three mid-step children: 1502 ms  (charged sequentially, scales per child)
control, fast/legal child :    1 ms
```

Deterministic once entered; conditional only on whether the child is mid-step.
Standalone reproduction: `repro/R7-08_await_settled_for_snapshot_blocks_loop.py`.

## Environment

- Library commit: `221ce7c` (unreleased 0.8.1; `__version__` reports 0.8.0)
- Python: 3.13.7
- Engine: async only (`Interpreter`)

## Minimal reproduction

See `repro/R7-08_await_settled_for_snapshot_blocks_loop.py` — a byte-for-byte
copy is kept alongside this issue. A parent `Interpreter` invokes a child
machine; the child is driven fire-and-forget into a 500 ms `async def`
action, then the parent's `get_persisted_snapshot()` is called and the wall
time to return is measured. Exits 1 while the call blocks for >=300 ms, 0
once fixed.

## Observed

```
parent snapshot over a mid-step ASYNC child: snapshot returned: {'p:kid': {...'state_ids': []...}} after 501 ms
```

## Expected

XState v5's `getPersistedSnapshot()` is non-blocking by contract — snapshotting
never waits on other actors. Even granting the library's own bounded-wait
design for this case, a wait that runs on the same event loop the awaited
child needs in order to progress cannot be a bounded *wait* at all: on a
single-threaded loop it is definitionally unable to let the child make
progress, so it should either yield the loop (`await asyncio.sleep`) or not
wait at all.

## Root cause

`src/xstate_statemachine/base_interpreter.py:1273-1288`
(`_await_settled_for_snapshot`):
```python
deadline = time.monotonic() + timeout_s
while (
    self._step_in_flight()
    and not self._configuration_is_legal()
    and time.monotonic() < deadline
):
    time.sleep(0.0005)
```
called from `get_persisted_snapshot()` at `base_interpreter.py:1389-1394` on
the child branch (`if not self._configuration_is_legal():
self._await_settled_for_snapshot()`). `time.sleep` blocks the calling
thread; on the async engine that thread is the event loop thread, so the very
child whose settlement the wait is polling for cannot run its own coroutine
step until the wait itself gives up the thread — which it does not do until
`timeout_s` (default 0.5 s) elapses.

## Impact

General: any latency-sensitive async application sharing the event loop with
the interpreter (every timer, every inbound event, every other machine on
that loop) stalls for up to 0.5 s per mid-step child snapshotted, and the
wait accomplishes nothing — it is guaranteed to time out and return the
unsettled blob regardless. Order-management scenario: a supervisor
snapshotting a parent order-router while one of its child order actors is
mid-fill-processing freezes the entire event loop — including the timer that
would have completed that very fill — for half a second per child, worse
with more children, and still returns a torn snapshot at the end.

## Proposed fix

`await asyncio.sleep(...)` on the async path — and consider refusing
outright rather than waiting, since the wait cannot succeed on a
single-threaded loop.

## Acceptance criteria

- `test_child_snapshot_wait_yields_event_loop_async`: on the async engine, a
  parent's `get_persisted_snapshot()` call made while a child is mid-step in
  an `async def` action returns within one scheduling tick of the child's
  completion (not a fixed ~0.5 s), and the returned child snapshot reflects
  the settled state.
- `test_child_snapshot_wait_does_not_block_other_coroutines`: while the
  parent's snapshot wait is in progress, an unrelated coroutine on the same
  loop (e.g. a timer callback) is observed to run — proving the loop was not
  blocked.
- `test_sync_child_snapshot_wait_unaffected` (regression guard): the sync
  engine's equivalent wait (thread-based, not loop-based) is unchanged.

## Not refutable

Undocumented (the docs describe the mid-step refusal, never a blocking wait); not
API misuse (parent settled, documented call site, no supported way to drain a
child's step first); XState v5's `getPersistedSnapshot()` is non-blocking.

## Related

Same class as R7-05 / R7-07 (the async engine's mid-step refusal has residual
windows), and specifically the mechanism meant to remedy R7-07's child-branch
tearing — see round 6 #169's root-only refusal.

## Verification

- Date: 2026-09-20
- Python: 3.13.7
- Commit: 221ce7c
- Command: `python repro/R7-08_await_settled_for_snapshot_blocks_loop.py`
- Exit code: 1 (reproduced — event loop blocked 501 ms)
