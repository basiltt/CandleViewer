---
r6: R6-12
title: "Bug: `_threadsafe_self_sends_in_flight` is incremented on the calling thread and decremented inside `_deliver`, so it leaks permanently if `_deliver` never runs — and it gates the `_raise_depth` reset"
labels: [bug, severity/medium, area/interpreter]
severity: Medium
engines: async
repro_script: repro/R6-12_threadsafe_self_send_counter_leak.py
commit: cec108b
python: 3.13.7
verified: true
---

## Summary

```
in-flight counter after loop stop: 5   (expected 0)
```

Incremented at `interpreter.py:1132` on the **calling thread**, decremented at `:1136`
**inside `_deliver`**. There is no compensating path if `_deliver` never runs — a stopped
loop, a refused enqueue, a cancelled future. The leak is deterministic and reproduces
every run.

## Why it matters beyond tidiness

The counter gates the `_raise_depth` reset at `interpreter.py:1513`. A permanently
non-zero value means the chain budget can never reset, so a long-lived machine would
eventually trip `RunawayChainError` on entirely legitimate work.

## Honest scoping

We could **not** drive that trip. `p10_counter_leak.py` failed to produce one, because
external events do not increment `_raise_depth` in the first place. So the consequence is
**latent, not demonstrated** — we are filing the leak, which is certain, and flagging the
consequence, which is a reading of the code rather than an observation.

## Suggested fix

Decrement in a done-callback attached to the returned future, so every terminal outcome
of the send — delivered, refused, cancelled, loop gone — balances the increment.

---

*Filed as part of adoption audit #26, round 6, against `main` @ `cec108b` (unreleased
0.8.1 — `__version__` still reports `0.8.0`, so this is keyed on the commit). Reproduced
in a fresh process against a clean venv before filing. CPython 3.13.7, Windows 11.*
