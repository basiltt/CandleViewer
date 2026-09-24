---
r8: R8-11
title: "Docs/Bug: #179's service-kind lap-parity claim is false for `invoke` ping-pong and rollback + `onDone` — sync and async cut the same chart at different lap counts"
labels: [bug, severity/medium, area/interpreter]
severity: Medium
engines: both engines
service_kinds: both
repro_script: repro/R8-11_service_kind_lap_parity.py
commit: 6db65d8
python: 3.13.7
verified: true
---

## Summary

#179's CHANGELOG claim — that both service kinds now trip at the same lap count as the sync
engine — is **false for `invoke` ping-pong and for rollback + `onDone`**. The fix itself is
real and valuable; the parity sentence is wider than what shipped.

## Reproduction (`6db65d8`)

`repro/R8-11_service_kind_lap_parity.py` drives the two shapes on both spellings and both
engines and prints the lap counts side by side. The ping-pong and rollback + `onDone`
shapes cut at different lap counts across sync and async; the shapes the pinned tests cover
do agree, which is why the suite is green.

For contrast, the shapes where parity **does** hold are striking and worth recording: on
the real control machines, `maxIterations` 2 / 5 / 100 gives 4 / 7 / 102 service calls,
`max + 2` exactly, **identical cell for cell** on `def` and `async def`. That is the claim
working. It just does not generalise to these two shapes.

## What we are asking for

Either close the gap, or narrow the CHANGELOG line to the shapes that are actually pinned.
We would rather have a precise claim than a broad one — our gate keys on these statements,
and round 7's experience is that a claim broader than its test is how a defect gets closed
while it is live.

## Suggested regression test

The two shapes above, parametrised over (engine × service kind), asserting **equal lap
counts**, not merely "both terminate".

## Verification

2026-09-21, python 3.13.7, commit 6db65d8.

Fresh run of `repro/R8-11_service_kind_lap_parity.py` — exit 0, `VERDICT: FAIL`:

```
=== invoke_pingpong
  [invoke_pingpong sync ] tripped=True  laps=28
  [invoke_pingpong def  ] tripped=True  laps=27
  [invoke_pingpong async] tripped=False laps=1  (after +1s: laps=27, still_turning=True)

=== rollback_ondone
  [rollback_ondone sync ] tripped=False laps=0
  [rollback_ondone def  ] tripped=True  laps=0
  [rollback_ondone async] tripped=False laps=0

FAILURES:
  - invoke_pingpong: `def` trips, `async def` does not (#179)
  - invoke_pingpong: sync=28 vs async-engine def=27 laps
  - rollback_ondone: `def` trips, `async def` does not (#179)
```

Confirms the draft's claim: on `invoke` ping-pong, the sync engine trips at 28 laps, the
async engine's `def` lane trips at 27 (a **different** count, not merely "both trip"), and
the async engine's `async def` lane has not tripped at all after 1s of settle time — it is
still turning. On rollback + `onDone`, only the async engine's `def` lane trips; sync and
`async def` do not. Both shapes contradict a same-lap-count parity claim across service
kinds and, for `invoke` ping-pong, across engines as well.

For contrast, the control-machine shapes the repro also drives (`maxIterations` 2/5/100 →
4/7/102 service calls) are identical cell-for-cell across `def`/`async def` in this same run,
confirming the parity claim does hold for the pinned/tested shapes and narrows precisely to
the two shapes above being outside its coverage.
