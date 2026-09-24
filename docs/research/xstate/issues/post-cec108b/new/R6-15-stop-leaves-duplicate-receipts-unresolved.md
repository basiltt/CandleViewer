---
r6: R6-15
title: "Regression: `stop()` does not resolve every outstanding duplicate-`Event`-instance receipt with `InterpreterStoppedError` — some racing events settle as ordinary success receipts"
labels: [bug, severity/medium, area/interpreter]
severity: Medium
engines: async
repro_script: repro/R6-15_stop_leaves_duplicate_receipts_unresolved.py
commit: cec108b
python: 3.13.7
verified: true
---

## Summary

**Regression against `5e07ba8`**, reproduced 5/5 deterministically.

Cases A, B and C of the original duplicate-`Event`-instance collision bug are
**genuinely fixed** — fresh and reused-instance concurrent `send()` / `send_threadsafe`
all now resolve correctly, and we are glad to see it.

Case D regressed: `stop()` no longer resolves *every* outstanding duplicate-instance
receipt with `InterpreterStoppedError`. Some events that raced the stop land as ordinary
`Receipt(changed=True, ...)`.

## Why it matters

A caller awaiting a receipt across a shutdown cannot distinguish "this was applied" from
"this was abandoned" for the racing window. For an order submission that is the wrong
kind of ambiguity: the safe reading of a stopped interpreter is that nothing after the
stop happened, and a success receipt asserts the opposite.

## Ask

Resolve all outstanding receipts at `stop()`, including duplicate `Event` instances, with
`InterpreterStoppedError`. A pinned test for case D specifically — the existing coverage
passes on A/B/C.

---

*Filed as part of adoption audit #26, round 6, against `main` @ `cec108b` (unreleased
0.8.1 — `__version__` still reports `0.8.0`, so this is keyed on the commit). Reproduced
in a fresh process against a clean venv before filing. CPython 3.13.7, Windows 11.*
