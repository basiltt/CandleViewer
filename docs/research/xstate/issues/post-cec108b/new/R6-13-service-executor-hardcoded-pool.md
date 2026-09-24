---
r6: R6-13
title: "Feature/bug: `_get_service_executor()` hard-codes `ThreadPoolExecutor(max_workers=4)` with no public `service_pool_size=`, so >4 concurrent plain-`def` services serialise in waves"
labels: [bug, severity/medium, area/services]
severity: Medium
engines: async
repro_script: repro/R6-13_service_executor_hardcoded_pool.py
commit: cec108b
python: 3.13.7
verified: true
---

## Summary

`interpreter.py:2360` constructs `ThreadPoolExecutor(max_workers=4)`. The limit is not
on the public surface and is not documented. Concurrency shows a clean step function at
multiples of 4:

```
n <= 4   : 0.22 s
n = 5-8  : 0.41 s
n = 12   : 0.62 s
```

Worse, it compounds: 9 x 0.2 s services took **5.01 s** against an ideal of 0.2 s and a
fully serialised 1.8 s — i.e. **worse than serial**, because each wave also blocks a
macrostep.

## Scoping

Medium, not High, because a workaround exists and works: passing an explicit
`service_executor=` overrides the pool entirely. We now set it unconditionally.

## Ask

A `service_pool_size=` argument, and a documented statement of the default limit and its
interaction with macrostep blocking. Right now a user who never reads the source has no
way to know that the fifth concurrent service waits.

---

*Filed as part of adoption audit #26, round 6, against `main` @ `cec108b` (unreleased
0.8.1 — `__version__` still reports `0.8.0`, so this is keyed on the commit). Reproduced
in a fresh process against a clean venv before filing. CPython 3.13.7, Windows 11.*
