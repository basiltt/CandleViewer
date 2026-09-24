---
r8: R8-05
title: "Bug: `DoneEvent` / `AfterEvent` carry no provenance marker and are exempt from `strict` / `onUnhandled` — a forged completion drives a real `onDone`, including one reconstituted from a snapshot blob"
labels: [bug, severity/high, area/events]
severity: High
engines: both engines
service_kinds: both (different failure mode on each)
repro_script: repro/R8-05_doneevent_forgery.py, repro/R8-05_doneevent_forgery_via_snapshot.py
commit: 6db65d8
python: 3.13.7
verified: true
---

## Summary

`DoneEvent` and `AfterEvent` are publicly exported, publicly documented NamedTuples with
**no provenance field**. `is_system_event` (`events.py:280`) returns `True` for them on a
bare `isinstance` check, so they are exempt from `strict` and `onUnhandled` — which means
any caller can construct one and drive a real `onDone` transition while the genuine service
is still running.

The documented invariant at `docs/api/index.md:1193` is "provenance, not name". That
invariant is false for precisely the two classes whose whole purpose is to assert engine
authorship.

## Reproduction (`6db65d8`)

`repro/R8-05_doneevent_forgery.py` → `VERDICT: FAIL`, 6 failures, both service kinds.

* On the `async def` path the forged `DoneEvent` **fires `onDone`** while the real service
  is still outstanding.
* On the `def` path it is a *second* failure mode, not immunity: the forged event is
  accepted as trusted and then discarded unmatched via the executor lane
  (`_finish_plain_service`) — silent loss, with neither a transition nor a `strict` /
  `onUnhandled` error. Timing was ruled out: 0.5 / 1.0 / 2.0 s settles against an 8 s
  service all swallow it, and the loop is not blocked.

`repro/R8-05_doneevent_forgery_via_snapshot.py` shows the escalating vector:
`restore_event` (`events.py:392`) reconstitutes a **trusted** `DoneEvent` from an
attacker-authored snapshot record, with no integrity check over `pending_events`, and that
object then drives `onDone` on a live machine. This is a wire vector, not only in-process
misuse.

## Why the usual refutations do not apply

* **Not API misuse.** Both classes are in `__all__`, documented with field tables, and
  accepted by `send()`'s own type signature. Contrast #85, which deliberately *removed*
  `Event`'s public `system=` parameter rather than documenting it away — the same treatment
  never reached these two.
* **No correct alternative exists.** `system_event()` mints a plain `Event` only; there is
  no engine-only factory for the NamedTuples.
* **XState v5 disagrees.** v5 binds `onDone` to the child actor's lifecycle. This port
  matches on name plus `event.src == inv.id` (`base_interpreter.py:4484`) with **no liveness
  check**, which is what lets a forgery land against a running service.
* **Not a duplicate.** #79 / #85 / #137 / #180 all terminate at the `Event` dataclass; #162
  covered only v1 snapshot name-laundering.

## Suggested fix

Three independent, each useful on its own:

1. Give `DoneEvent` / `AfterEvent` a private provenance field set only by the engine, and
   make `is_system_event` read it instead of `isinstance`.
2. Add a liveness check at `base_interpreter.py:4484`: a `done.invoke.<id>` only matches if
   `<id>` names an invocation that is actually outstanding.
3. Strip (or refuse) completion events in `pending_events` on restore, or cover
   `pending_events` with the blob's integrity check.

## Impact

A forged `done.invoke.<fill-service>` commits arbitrary data — a fabricated fill price and
quantity — into context while the real venue call is still outstanding. Under `def`
services, `strict` fails as a detection control at the same time.

## Verification

2026-09-21, python 3.13.7, commit 6db65d8.

`repro/R8-05_doneevent_forgery.py` — exit 0, `VERDICT: FAIL`, 6/6 failures reproduced
(3 `def`-lane exemptions from `strict`/`onUnhandled`, 3 `async`-lane exemptions, with the
`async` `DoneEvent('done.invoke.k')` case additionally driving `onDone`
(`['sec.a'] -> ['sec.done_']`) while the real service is still outstanding). Surface check
confirmed: `DoneEvent`/`AfterEvent` have no `.system`/`._provenance` attribute and are plain
`tuple`, while `Event` has both.

`repro/R8-05_doneevent_forgery_via_snapshot.py` — exit 0, confirmed: `restore_event()` on an
attacker-authored record (`{"kind":"done","type":"done.invoke.k","data":{"forged":true,
"px":9000000000.0},"src":"k"}`) reconstitutes a `DoneEvent` with `is_system_event=True` and no
integrity check, and on the async engine it drives `['sec.a'] -> ['sec.done_']` with
`ctx.got={'forged': True, 'px': 9000000000.0}`.

Source confirmed at commit 6db65d8: `is_system_event` (`events.py:272`) does a bare
`isinstance(event, ENGINE_EVENT_TYPES)` check; the invoke-completion match at
`base_interpreter.py:4484` (`if isinstance(event, (DoneEvent, ErrorEvent))`) checks only
`event.src == inv.id` with no liveness check.
