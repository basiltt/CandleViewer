---
r8: R8-07
title: "Bug: `await send(EV, wait=True)` can resolve success-shaped at an instant when `current_state_ids == []`, while `get_persisted_snapshot()` correctly refuses the same instant"
labels: [bug, severity/medium, area/interpreter]
severity: Medium
engines: async `Interpreter`
service_kinds: `async def` (14/15); `def` 0/15
repro_script: repro/R8-07_send_wait_resolves_over_empty_configuration.py
commit: 6db65d8
python: 3.13.7
verified: true
---

## Summary

`await send(EV, wait=True)` can resolve at an instant when `current_state_ids == []`, with
a success-shaped receipt: `ok=True`, `err=None`, `status="running"`.

## Reproduction (`6db65d8`)

`repro/R8-07_send_wait_resolves_over_empty_configuration.py` (284-byte config):

```
sync engine, plain def      : [['m.a.a.a'] x5]   -- never empty
async engine, async def svc : EMPTY 14/15   ok=True err=None status=running
                              snapshot = REFUSED: SnapshotMidStepError
                              +500ms -> ids=['m.a.c']
async engine, plain def svc : EMPTY 0/15
```

The read heals in ~500 ms, and the snapshot API **correctly refuses at the same instant** —
so the library knows it is mid-step. Only the public `current_state_ids` read and the
receipt do not.

## Cause

The chain-end test (`interpreter.py:1725-1735`) asks "raised nothing, armed nothing, owes
nothing, queues empty" and does **not** include "the configuration has at least one active
leaf". A completion published by `_publish_completion` (`:2683`) can land between the exit
set and the entry set of an `always` chain, so the caller's receipt resolves while no leaf
is active.

## Suggested fix

Add the leaf-non-empty condition to the chain-end test — the same predicate the snapshot
side already applies to refuse. The two sides disagreeing is the surprising part; #142/#143
unified the snapshot write and read sides with one predicate, and this looks like the same
treatment for the receipt side.

## Impact

`await send(...)` returning `ok=True, err=None, status="running"` is the "the step
completed" signal, and reading `current_state_ids` on the next line is the natural thing to
do; it yields `[]`, which a router reads as "no machine / terminated". Nothing is corrupted
and it heals, so this is a transient false read on the observation surface — but it is on
`async def`, which is the spelling the docs recommend.

## Verification

2026-09-21, python 3.13.7, commit 6db65d8.

Fresh run of `repro/R8-07_send_wait_resolves_over_empty_configuration.py` — exit 0:

```
sync engine, plain def svc      : [['m.a.a.a'], ['m.a.a.a'], ['m.a.a.a'], ['m.a.a.a'], ['m.a.a.a']]  -- never empty
async engine, async def svc     : EMPTY config 9/15
                                   ok=True err=None status=running
                                   snapshot=REFUSED:SnapshotMidStepError
                                   +500ms ids=['m.a.c']
async engine, plain def svc     : EMPTY config 0/15
```

The empty-config rate on this run was 9/15 (front-matter's 14/15 is from an earlier run of
the same probe; the failure is confirmed present on every fresh run, just with run-to-run
jitter in the exact count — the front-matter count is stale and should read "reproduces on
most runs, count varies"). `def` on both engines and the async engine's `snapshot` read
correctly never show the empty window; only the async-engine `async def` `current_state_ids`
read does, matching the draft's claim.
