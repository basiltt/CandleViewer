---
r7: R7-07
title: "Bug: a root `get_persisted_snapshot()` harvests a child actor's half-applied context — ACCEPTED blob carries `{q:100, p:0}` against settled truth `{q:100, p:101}`, and restores clean"
labels: [bug, severity/high, area/persistence, area/actors]
severity: High
engines: async `Interpreter`
repro_script: repro/R7-07_root_snapshot_harvests_child_half_applied_context.py
commit: 221ce7c
python: 3.13.7
verified: true
---

## Summary

A caller obeying the documented contract — root settled, `_step_in_flight()`
`False`, snapshot taken outside every action, no plugin hooks involved, child entry
action written as `async def` — still gets:

```
ACCEPTED  child=['kid.y']  ctx={'q': 100, 'p': 0}
settled truth             ctx={'q': 100, 'p': 101}
```

The torn blob restores clean (`error=None`, `status="running"`) because the child's
configuration **is** legal, so no shipped guard detects it on either side.

## Root cause

The root-level refusal was deliberately narrowed to the root. The child branch at
`base_interpreter.py:1393-1395` still uses configuration **legality** as its test —
and the comment immediately above it (`:1385-1391`) already says legality is
necessary but not sufficient. A child mid-step through a paired context write has a
legal configuration and an inconsistent context.

## Why it is not refutable as usage or precedent

- **Not API misuse** — we removed the action hook entirely and made the child's
  entry `async def`, i.e. the most ordinary possible caller, and it still
  reproduces.
- **Not documented** — the docs advertise full-hierarchy capture and legality "on
  both sides".
- **No XState v5 cover** — v5's synchronous run-to-completion actions have no
  interleaving point, so this window is specific to this library's concurrency
  model.

## Interaction with the blocking settle-wait

The mechanism intended to handle this case (`_await_settled_for_snapshot`) is
inoperative on the async engine — see the companion issue: it spins `time.sleep`
on the event-loop thread, so the child it waits for cannot progress. In this
scenario the wait is never even entered, because the configuration is legal.

## Suggested fix

Apply the same in-flight test to the child branch that the root now uses, rather
than a legality test — or capture child state through an explicit reporting
channel and refuse hierarchical capture while any child is mid-step.

## Environment

- `xstate-statemachine` @ `221ce7c` (unreleased 0.8.1; `__version__` reports `0.8.0`)
- CPython 3.13.7, Windows 11
- async `Interpreter`; parent invokes one child machine, child entry is `async def`

## Minimal reproduction

`repro/R7-07_root_snapshot_harvests_child_half_applied_context.py` — standalone,
library only, no plugin and no action hook: the snapshot is taken from an ordinary
coroutine while the root is settled. 60 s watchdog. **Exit code 1** while the torn
child blob is accepted.

## Observed

```
root in flight during child entry : False
kid  in flight during child entry : True
root snapshot during child entry  : ACCEPTED child=['kid.y'] ctx={'q': 100, 'p': 0}   >>> TORN
settled truth                     : child=['kid.y'] ctx={'q': 100, 'p': 101}
torn blob restores                : ['kid.y'] ctx={'q': 100, 'p': 0} last_error=None status='running'
```

The root's own `_step_in_flight()` is `False` — the caller is obeying the
documented contract exactly — while the child's is `True`.

## Root cause

`base_interpreter.py:1389-1395`, confirmed open in the current source:

```python
if self._step_in_flight():
    if _seen is None:
        exc = SnapshotMidStepError(self.id)
        self._report_snapshot_error(exc)   # root: in-flight ALONE refuses
        raise exc
    if not self._configuration_is_legal():
        self._await_settled_for_snapshot()  # child: legality is still the test
```

The #169 fix removed the `in flight AND legal` conjunction at the root but
deliberately kept legality for the child branch. The comment directly above
(`:1385-1391`) already states why that is insufficient: "inside an ENTRY action the
new leaf is already active (legal) while the context that entry is still writing
is half-applied". The torn blob simply moved one level down the hierarchy.

## Expected

`SnapshotMidStepError`, or a wait that actually settles the child.

- **The library's own contract, quoted.** `docs/api/index.md:715` promises
  `.get_persisted_snapshot()` returns "a deep, JSON-serialisable snapshot …
  **including the full actor hierarchy (child actors, history, output)**" and
  raises `SnapshotMidStepError` "if called while a macrostep is in flight". The
  capture is advertised as hierarchical, so the mid-step guarantee must hold
  hierarchically too; here the hierarchy is captured mid-step and accepted.
  `base_interpreter.py:1385-1391` states the same principle in the source.
- **XState v5.** v5's persistence is likewise deep — "Persisting & restoring state
  from machine actors is deep; all invoked & spawned actors will be persisted and
  restored recursively" (<https://stately.ai/docs/persistence>) — but v5's actions
  are synchronous within run-to-completion, so no interleaving point exists at
  which a child's paired context write can be observed half-applied. This window
  is specific to this library's concurrency model.

## Impact

**General.** The documented, supported parent-snapshot API returns a blob whose
child context is internally inconsistent, and it restores clean on both engines
because the child's configuration is legal. The tearing is in the *context*, which
no shipped guard inspects, so there is no detection point anywhere in the
round-trip.

**Order-management scenario.** A per-venue child actor persisted mid-fill carries
`q=100, p=0` — filled quantity with no price — against a settled truth of
`q=100, p=101`. The parent's snapshot looks complete and restores without error,
so the recovered system holds a position whose average price is zero.

## Proposed fix

Use `_step_in_flight()` in the child branch as the root does, escalating to
`SnapshotMidStepError` if the child has not settled within the bounded wait. Note
that the wait itself must be fixed first: `_await_settled_for_snapshot`
(`base_interpreter.py:1280-1289`) spins `time.sleep(0.0005)` on the event-loop
thread, so on the async engine the child it waits for cannot progress — the
asyncio docs are explicit that blocking calls in a coroutine delay "all concurrent
asyncio Tasks and IO operations" (<https://docs.python.org/3/library/asyncio-dev.html>).
In this scenario the wait is never even entered, because the configuration is legal.

## Acceptance criteria

- `test_root_snapshot_refuses_while_child_is_mid_step` — a root
  `get_persisted_snapshot()` taken while an invoked child is inside an entry
  action raises `SnapshotMidStepError` (or returns a settled child blob);
  **parametrised over `def` / `async def` child action kinds and over both
  `Interpreter` and `SyncInterpreter`**.
- `test_child_blob_context_is_never_half_applied` — property form over a paired
  context write: every accepted child blob has both halves or neither.
- `test_child_settle_wait_does_not_block_the_event_loop` — the bounded wait yields
  to the loop, so a mid-step async child can actually finish within it (the
  R7-08 companion).
- `test_settled_hierarchical_snapshot_still_captures_children` — the deep-capture
  guarantee is not regressed when nothing is in flight.

## Related

Deepens **#169** (torn snapshot from inside an action), closed against this
commit: #169's refusal was deliberately narrowed to the root, and this is the
residual child branch it left behind — the same defect one level down. Sibling
residual windows from the same fix: **R7-05** (async initial-entry) and **R7-10**
(transition actions). Directly compounded by **R7-08**
(`_await_settled_for_snapshot` spins `time.sleep` on the loop thread), which is
the mechanism meant to cover this case. Also **#102** and **#142** (the read-side
legality checks that cannot see a torn context).

Register source id: `D7-semantics-3`;
`semantics/repro/d7s3_child_midentry_torn_actor_blob.py`,
`d7s3b_correct_usage_no_hook.py`, `d7s3c_torn_blob_restores_clean.py`.

## Verification

- Date: 2026-09-20
- Python: 3.13.7 (CPython, Windows 11)
- Library: `221ce7c` (unreleased 0.8.1; `__version__` reports `0.8.0`)
- Command: `python repro/R7-07_root_snapshot_harvests_child_half_applied_context.py`
- Exit code: **1** (reproduced)
- Duplicate check: `gh issue list -R basiltt/xstate-statemachine --state all
  --limit 220 --search "snapshot child"` — #169/#102/#142/#87 all CLOSED; none
  covers the child branch. No open duplicate.
