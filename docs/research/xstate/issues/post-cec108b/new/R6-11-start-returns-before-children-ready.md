---
r6: R6-11
title: "Bug: `await Interpreter.start()` returns before the initial entry set's `invoke` children are registered and before an initial plain-`def` service completes; `SyncInterpreter.start()` does both"
labels: [bug, severity/medium, area/interpreter]
severity: Medium
engines: async (SyncInterpreter is correct)
repro_script: repro/R6-11_start_returns_before_children_ready.py
commit: cec108b
python: 3.13.7
verified: true
---

## Summary

`await Interpreter.start()` returns while the initial macrostep is still settling. Three
independently written probes land on one root cause.

```
async_completes_inside_start : false
sync_completes_inside_start  : true
engines_agree_on_start_completion : false

async: actors immediately after `await start()` : []
async: child actor became addressable 12.7 ms AFTER start() returned
async: first POKE -> drops: ['unresolved_target']
sync : actors immediately after start() : ['par:kid']   (0 lost in 10)
```

## Root cause

`interpreter.py:487,496`. `start()` enters the initial configuration via `_enter_states`
+ `_settle_transient_transitions` and **never calls `_await_inline_services()`**, which
is only reached from the run loop at `:1645`/`:1649`. So the executor handoff future
created at `:2417-2425` is first drained by the *first event's* macrostep, and
invoke-child registration lands after `start()` has returned.

## Why the existing pin does not catch it

The `(GO, CANCEL) x10` #116 parity oracle passes (`sync=ok10 async=ok10`), so the pinned
regression test is green while the engines disagree on what `start()` means.

## Mitigating, and why it is still worth fixing

The `sendTo` loss is **not silent** — `on_event_dropped(reason='unresolved_target')` plus
a soft step error fire, which is the #133 contract working correctly. But
`await start()` reads as *"the machine is up and its declared children exist"*, and the
two engines disagree about that for the same configuration.

## Ask

Either await the initial macrostep's inline services and actor registration inside async
`start()`, or expose an awaitable `children_ready()` and document that `start()` does not
imply it. We have implemented the latter as a wrapper on our side and would happily drop
it.

---

*Filed as part of adoption audit #26, round 6, against `main` @ `cec108b` (unreleased
0.8.1 — `__version__` still reports `0.8.0`, so this is keyed on the commit). Reproduced
in a fresh process against a clean venv before filing. CPython 3.13.7, Windows 11.*
