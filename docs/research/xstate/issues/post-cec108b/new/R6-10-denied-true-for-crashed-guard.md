---
r6: R6-10
title: "Bug: `Receipt.denied` is `True` for a guard that *crashed* under `guardErrorPolicy: "raise"`, mislabelling a third case into the bucket #153 exists to separate"
labels: [bug, severity/medium, area/receipts]
severity: Medium
engines: both
repro_script: repro/R6-10_denied_true_for_crashed_guard.py
commit: cec108b
python: 3.13.7
verified: true
---

## Summary

A guard that **raises** under `guardErrorPolicy: "raise"` yields `Receipt.denied=True`,
because `_is_guard_satisfied` returns `False` on the raise path
(`base_interpreter.py:4834`) and that sets `_guard_denied_this_step`. Reproduced on both
engines.

The documentation says `denied` means the guard *"returned False"*
(`docs/api/index.md:1222`, `docs/_guide/interpreters.md:510`). A crash is a third,
never-enumerated case.

## Why we filed this at Medium rather than High

We tried hard to break it and it mostly held up:

- **#153's actual contract is intact.** Declared-but-refused vs undeclared still works;
  an undeclared event still gives `denied=False`. This is a third case mislabelled into
  the denial bucket, not a re-merge of the two #153 separates.
- **No information is lost.** `Receipt.error` is a documented first-class field on the
  same object, and `(denied, error is None)` totally discriminates all three cases in a
  single read. Being misled requires reading `denied` while ignoring a non-`None` `error`.
- **The plugin channel is clean.** A crashed guard under `"raise"` fires no
  `on_unhandled_event` at all, so the `"guard_denied"` disposition is un-conflated.

Note also that two harness errors of our own had to be corrected before this reproduced
at all (`logic_modules=[class]` is invalid; sync `send()` needs `wait=True` to return a
`Receipt`) — flagging that so the repro is read correctly.

## The `defer` half, stated accurately

Under `onUnhandled: "defer"` the receipt reports `denied=True` **and** `deferred=True`
together, so the denial is **not** shadowed where the caller reads it — only the
single-valued plugin disposition string has to pick one label. And a guard-denied event
entering the defer buffer and being replayed later against a changed world is `defer`
performing its documented function over "an event selected no transition"; scoping
`defer` machine-wide on a chart with business-rule guards is **our** configuration
choice to fix, not a library defect. We mention it only because the combination
surprised us.

XState v5 has neither `Receipt` nor `onUnhandled` and grants no authority either way.

## Ask

Either make `denied` `False` when the guard raised, or document `error is None` as the
discriminator. A one-line note that denied events enter the defer buffer and are
re-evaluated later would also have saved us an afternoon.

---

*Filed as part of adoption audit #26, round 6, against `main` @ `cec108b` (unreleased
0.8.1 — `__version__` still reports `0.8.0`, so this is keyed on the commit). Reproduced
in a fresh process against a clean venv before filing. CPython 3.13.7, Windows 11.*
