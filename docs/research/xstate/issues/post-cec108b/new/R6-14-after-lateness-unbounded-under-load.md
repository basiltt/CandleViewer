---
r6: R6-14
title: "Regression: `after` timer lateness is 88-92 ms against a 50 ms budget under a busy loop — the per-macrostep settle budget bounds iterations but not lateness"
labels: [bug, severity/medium, area/timers]
severity: Medium
engines: both
repro_script: repro/R6-14_after_lateness_unbounded_under_load.py
commit: cec108b
python: 3.13.7
verified: true
---

## Summary

**Regression against `5e07ba8`**, reproduced 5/5 deterministically.

The `AfterEvent` timestamp *fields* are correctly populated (#118 is genuinely fixed —
we have confirmed that separately and asked for #118 to be closed). What regressed is
the lateness itself: under a 100-iteration busy loop, observed lateness is **88-92 ms**
against a 50 ms budget.

The round-5 CHANGELOG describes a *"per-macrostep settle budget"*, which we read as
bounding the delay a timer can suffer. It bounds iterations per macrostep, but not
lateness under load.

## Note on severity

Medium for us because we already constrain `after` to coarse, non-critical timeouts and
drive all latency-sensitive timing from an external monotonic scheduler — a constraint
we adopted for an earlier finding. For a user who takes `after` at face value for, say,
a 50 ms heartbeat, the observed behaviour is a doubling.

## Related

A second, independent probe (`after.100` firing at 0.528 s while a 0.5 s plain-`def`
service is in flight, ~428 ms late) shows the same class from the services direction.
That one is arguably by design given the documented macrostep semantics, but it is not
documented as a timing consequence anywhere we could find.

---

*Filed as part of adoption audit #26, round 6, against `main` @ `cec108b` (unreleased
0.8.1 — `__version__` still reports `0.8.0`, so this is keyed on the commit). Reproduced
in a fresh process against a clean venv before filing. CPython 3.13.7, Windows 11.*
