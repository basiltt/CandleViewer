---
lc: F-2
title: "Bug: the `sync=` compatibility shim treats a `**kwargs` clock as consent and feeds it an unexpected keyword (#76)"
labels: [bug, severity/high, area/clock, backwards-compatibility, candleviewer]
severity: High
blocks_adoption: false
verified: true
status: still-present
retested_on: main@3c527b0 (2026-09-18, after PR #83)
repro_script: new-main/repro/f_clock_kwargs.py
library_version: main@3c527b0
python: 3.13.7
found_by: main @ 5327ba6 diff review (19-verify-main-diff-review.md F-2)
related_issue: "#76, #50"
---

## Summary

The #76 fix adds a `sync=` kwarg to `Clock.set_timeout` and, to stay compatible
with clocks written against the 0.8.0 protocol, inspects `set_timeout`'s
signature once at construction to decide whether to pass it.

`_accepts_kwarg` returns `True` when **any** parameter is `VAR_KEYWORD`:

```python
return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
```

A clock written against the **0.8.0** protocol —
`def set_timeout(self, fn, delay_sec, **kwargs)`, a completely ordinary shape
for a wrapper forwarding to a legacy scheduler — is therefore judged to
"accept" `sync`, and is handed a keyword it has never heard of.

A 0.8.0-era clock cannot have consented to a keyword that did not exist when it
was written. The CHANGELOG's promise — *"third-party clocks written against the
0.8.0 `Clock` protocol still work"* — does not hold for this shape.

## Environment

- Library: `xstate-statemachine`, local clone, `main` @ commit
  `5327ba69fb735cfe24c7b3772050dac0a71a7b3d`, `pip install -e .`
- Python: 3.13.7 (CPython) · Windows 11 x64 (10.0.26200)

## Location

`src/xstate_statemachine/base_interpreter.py:275-291` (`_accepts_kwarg`) and
`:3435-3449` (`_set_timeout`).

## Minimal reproduction

A `**kwargs` clock that asserts on unknown keys — standing in for any wrapper
forwarding `**kwargs` to a backend with a fixed signature:

```python
class LegacyWrapperClock:
    def set_timeout(self, fn, delay_sec, **kwargs):
        assert not kwargs, f"unexpected kwargs: {sorted(kwargs)}"
        return self._backend.schedule(fn, delay_sec)
```

Full script: `repro/f_clock_kwargs.py`.

## Observed

```
AssertionError: unexpected kwargs: ['owner', 'sync']
  ... base_interpreter.py, in _set_timeout
      fn, delay_sec, owner=owner, sync=self._clock_sync_lane
```

The failure surfaces at the **first `after` / delayed send** — i.e. at runtime,
under load — not at construction.

## Expected

A clock that does not name `sync` as a parameter is called with the legacy
signature, exactly as one with an explicit two-positional-argument signature is.
`**kwargs` is not consent.

## Proposed fix

Require `sync` to appear **by name** in the signature:

```python
return "sync" in params and params["sync"].kind is not inspect.Parameter.VAR_KEYWORD
```

treating `VAR_KEYWORD` as *not* accepting it. Clocks that genuinely want the
kwarg can declare it; that is a one-line change on their side and the protocol
already documents it.

The single-call design that replaced 0.8.0's try/except-`TypeError` retry is
otherwise a real improvement (a clock's own `TypeError` now surfaces unchanged
instead of triggering a silent retry) — the defect is narrowly the
`VAR_KEYWORD` branch.

## Acceptance criteria

1. `repro/f_clock_kwargs.py` exits 0 — a `**kwargs` clock is called with the
   legacy signature and no `sync` / `owner` keyword.
2. A clock declaring `sync` explicitly still receives it, exactly once per
   timer, with the lane chosen by the owning engine.
3. A clock declaring `def set_timeout(self, fn, delay_sec)` still works
   (existing #76 behaviour, `repro/f_mixed_clock.py`).
4. Test: `test_kwargs_only_clock_is_called_with_legacy_signature`.
5. The `Clock` protocol docs state that `**kwargs` is not treated as accepting
   new protocol keywords, so third-party authors know how to opt in.


---

## Re-test on `main@3c527b0` (2026-09-18, after PR #83)

**Status: STILL-PRESENT.** PR #83 does not touch `base_interpreter._set_timeout` or the `sync=`
signature-inspection shim; the shim still passes `sync=` to any `set_timeout`
declaring `**kwargs`.
Repro re-run on `3c527b0` with the same interpreter and environment.

```
$ python repro/f_clock_kwargs.py
AssertionError: unexpected kwargs: ['owner', 'sync']
  (raised from base_interpreter.py:3451 -> clock.set_timeout(fn, delay, owner=..., sync=...))
```

See `../../23-verify-3c527b0-findings.md` for the full re-test table.
