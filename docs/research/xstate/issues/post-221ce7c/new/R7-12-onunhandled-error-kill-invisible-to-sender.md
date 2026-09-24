---
r7: R7-12
title: "Bug: the `onUnhandled: \"error\"` fatal kill is invisible to the sender — the caller gets a success-shaped `Receipt` for the event that just killed the interpreter"
labels: [bug, severity/medium, area/interpreter]
severity: Medium
engines: both
repro_script: repro/R7-12_onunhandled_error_kill_invisible.py
commit: 221ce7c
python: 3.13.7
verified: true
---

## Summary

Under `onUnhandled: "error"`, an unhandled event terminates the interpreter —
but the sender's `Receipt` is success-shaped, so the caller that caused the
kill cannot tell from the return value that anything happened. Standalone
reproduction: `repro/R7-12_onunhandled_error_kill_invisible.py`.

This is the same ergonomics class that was fixed by round-6 #153 adding
`Receipt.denied`, and it wants the same treatment: a discriminable field on
the receipt (`errored`, or a populated `error`) so a caller can branch on it.

It matters most for control-plane machines, where `onUnhandled: "error"` is
exactly the right policy for catching contract drift — and where an
operator-facing surface needs to report "your event was rejected and the
machine stopped", not "ok".

## Environment

- Library commit: `221ce7c` (unreleased 0.8.1; `__version__` reports 0.8.0)
- Python: 3.13.7
- Engine: both

## Minimal reproduction

See `repro/R7-12_onunhandled_error_kill_invisible.py` — a byte-for-byte copy
is kept alongside this issue. A one-state machine with `onUnhandled: "error"`
is sent an undeclared event with `wait=True` on both engines; the returned
`Receipt` and the interpreter's post-send `status`/`is_running` are compared.
Exits 1 while the killing send's own receipt is fully success-shaped, 0 once
fixed.

## Observed

```
async: before_running=True after_running=False receipt=Receipt(state_ids=frozenset({'p.a'}), changed=False, error=None, deferred=False, denied=False) last_error=None status=error
sync : before_running=True after_running=False receipt=Receipt(state_ids=frozenset({'p.a'}), changed=False, error=None, deferred=False, denied=False) last_error=None status=error
```
`is_running` correctly flips `True -> False` and `status` correctly becomes
`"error"` on both engines, but the `Receipt` returned to the very `send()`
call that caused it carries `error=None`, `denied=False`, `changed=False` —
indistinguishable from an ordinary no-op success.

## Expected

Round-6 #153 established the project's own precedent for exactly this
ergonomics gap: a guard-denied event and an undeclared event were previously
indistinguishable via `Receipt`, and the fix was to add a discriminable
`Receipt.denied` field so a caller does not have to poll `status` or
`last_error` out-of-band to learn what happened to the event it just sent.
The same principle — "the caller of `send()` should be able to tell from the
return value what happened to its own event" — applies here: the event that
triggers `onUnhandled: "error"`'s fatal kill is the most consequential
outcome `send()` can produce, and it is the one case currently invisible in
the receipt.

## Root cause

The unhandled-event kill path (reached via `_handle_unhandled_event` /
`_check_strict`'s `onUnhandled: "error"` disposition, both engines) populates
`self._last_action_error` and flips `status`/`is_running` as part of tearing
the interpreter down, but does not thread that error into the `Receipt`
object constructed for the triggering `send()` call — the `Receipt`
constructor is called with `step_error` computed from
`self.last_transition_ok`/`self._last_action_error` (see `interpreter.py`
around the receipt-building block and the equivalent in
`sync_interpreter.py`), and the unhandled-kill path exits before that
assignment happens (it fires `on_unhandled_event` and terminates the
interpreter instead of setting `_last_action_error`), so `step_error` stays
`None`.

## Impact

General: any caller relying on `Receipt` to learn what happened to its own
event — rather than polling `status` separately — is told nothing went
wrong when in fact the interpreter died. Order-management scenario: an
operator or upstream service sends a command to a control-plane machine
protected by `onUnhandled: "error"` specifically to catch protocol drift; the
send that trips the protection returns a clean receipt, so the caller has no
way to know from the call site that its own action just killed the machine,
and only a separate `status` poll (if one exists) would reveal it —
compounding any caller-side bug that ignores `status` after a "successful"
`send()`.

## Proposed fix

Populate `Receipt.error` (and/or add an explicit disposition, e.g.
`Receipt.errored: bool`, mirroring `Receipt.denied`) on the event that
triggers the fatal kill, before the interpreter tears down, so the triggering
`send()`'s own return value is discriminable from an ordinary no-op.

## Acceptance criteria

- `test_onunhandled_error_kill_receipt_discriminable[def]` and `[async def]`
  (both engines; parametrised over service kind is not directly applicable
  here since no service is invoked, but the machine variant should be tested
  on both `Interpreter` and `SyncInterpreter`): the `Receipt` returned by the
  `send()` call that triggers an `onUnhandled: "error"` kill has either
  `error is not None` or an equivalent `errored=True` flag.
- `test_onunhandled_error_kill_still_reports_status_and_last_error`
  (regression guard, both engines): `status` and `last_error` continue to
  reflect the kill as they do today.
- `test_onunhandled_error_non_killing_events_unaffected` (both engines): a
  normal handled event's `Receipt` is unchanged by this fix.

## Related

Round-6 #153 (`Receipt.denied` added for the guard-denied vs undeclared-event
ambiguity) is the direct precedent for this same class of gap. Register id
`LIB-01` (carried, unchanged on `221ce7c`).

## Verification

- Date: 2026-09-20
- Python: 3.13.7
- Commit: 221ce7c
- Command: `python repro/R7-12_onunhandled_error_kill_invisible.py`
- Exit code: 1 (reproduced — success-shaped receipt on both engines)
