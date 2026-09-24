---
lc: M-1
title: "Bug: `send(event, wait=True)` resolves with `changed=False, error=None` for an event held by `onUnhandled: \"defer\"`"
labels: [bug, severity/high, area/interpreter, candleviewer]
severity: High
blocks_adoption: true
verified: true
status: still-present
retested_on: main@3c527b0 (2026-09-18, after PR #83)
repro_script: new-main/repro/a2_confirm_deferred_receipt.py
library_version: main@3c527b0
python: 3.13.7
found_by: main @ 5327ba6 verification (21-verify-main-adversarial.md M-1, 22-verify-main-verdict.md section 2)
related_issue: "#28 (onUnhandled defer), #39/#75 (send receipts)"
---

## Summary

Two features that are individually correct are jointly wrong.

When `onUnhandled: "defer"` parks an event, the run loop still resolves that
event's `wait=True` receipt at the end of the macrostep, by comparing
configuration and context before/after. Nothing changed — because the event was
never processed — so the receipt reports `changed=False, error=None`.

That is **indistinguishable from "the machine looked at your event and correctly
decided to do nothing"**, for an event that is in fact parked and *will* drive
its transition on replay, after the caller has already acted on the receipt.

This is not a hang and not data loss. It is a gate that says *no* about an event
that is about to say *yes*.

## Environment

- Library: `xstate-statemachine`, local clone, `main` @ commit
  `5327ba69fb735cfe24c7b3772050dac0a71a7b3d`, `pip install -e .`
  (`__version__` reports `0.8.0`; CHANGELOG `[Unreleased] — targeting 0.8.1`)
- Python: 3.13.7 (CPython, MSC v.1944 64-bit)
- OS: Windows 11 x64 (10.0.26200)

## Minimal reproduction

```python
import asyncio
from xstate_statemachine import Interpreter, create_machine

CFG = {
    "id": "gate",
    "initial": "closed",
    "onUnhandled": "defer",
    "context": {"filled": 0},
    "states": {
        "closed": {"on": {"OPEN": "open"}},
        "open":   {"on": {"FILL": {"target": "filled", "actions": ["mark"]}}},
        "filled": {},
    },
}

async def main():
    i = Interpreter(create_machine(CFG, logic=LOGIC))
    await i.start()
    receipt = await i.send("FILL", wait=True)      # no FILL handler in `closed`
    print("changed =", receipt.changed)            # False
    print("error   =", receipt.error)              # None
    print("deferred=", i.deferred_count)           # 1   <- parked, and pending
    await i.send("OPEN")                           # replay
    print("states  =", i.current_state_ids)        # {'gate.filled'}

asyncio.run(main())
```

Full script with assertions: `repro/a2_confirm_deferred_receipt.py` (exits 0,
asserting the *defect* — it will need inverting once fixed).

## Observed

```
receipt at defer time:
  changed = False      <- the caller's gate says "nothing happened"
  error   = None       <- and "nothing went wrong"
  states  = ['gate.closed']
  deferred_count = 1   <- but the event is parked and pending

after OPEN (replay):
  states  = ['gate.filled']   <- the transition the receipt denied
  context = {'filled': 1}
```

## Expected

A receipt must be able to distinguish three outcomes, not two:

1. **processed, changed something** — `changed=True`
2. **processed, correctly no-op** — `changed=False, deferred=False`
3. **deferred, not yet processed** — the caller must not read this as (2)

Any one of these would resolve it:

- a `Receipt.deferred: bool` (or a tri-state `disposition`) set from the
  `defer` decision `_handle_unhandled_event` has already made; or
- resolving the receipt on **replay** instead of at defer time, so `wait=True`
  means "wait until this event is actually processed"; or
- at minimum, documenting loudly in the `onUnhandled` guide that a `wait=True`
  receipt is meaningless while `deferred_count > 0`.

Option 1 is the cheapest and preserves the existing timing contract.

## Cause

`interpreter.py` resolves the pending receipt at the end of the macrostep by
comparing configuration and context, with no knowledge of the `defer`
disposition that `base_interpreter._handle_unhandled_event` recorded
microseconds earlier. The two code paths never exchange that fact.

## Why this matters

For any caller that uses the two features together — which is the combination
the `defer` policy exists to make safe — a legitimate event arriving one
microstep early returns a confident "no". A caller that retries, or reports
failure and unwinds, does so against a machine that is about to succeed.

In our own adoption, both settings are *mandated* on the order path
(`onUnhandled: "defer"` + `send(wait=True)` for every gated decision), so the
composition is not an edge case for us — it is the normal path.

## Acceptance criteria

1. `repro/a2_confirm_deferred_receipt.py` inverted (assert `changed is False`
   **and** the deferral is discoverable from the receipt alone) exits 0.
2. A deferred event's receipt is distinguishable, from the receipt object
   alone, from a genuinely-processed no-op — without the caller having to read
   `interpreter.deferred_count` in the same instant.
3. On replay, the caller can learn the eventual outcome (either the original
   receipt resolves then, or the deferral is explicit enough that the caller
   knows to wait).
4. `onUnhandled: "error"` and `"ignore"` receipts are unchanged.
5. Tests: `test_receipt_reports_deferred_disposition`,
   `test_receipt_not_changed_is_distinguishable_from_deferred`.
6. The `onUnhandled` guide and the "Getting an answer from a machine" page both
   state the composed contract.


---

## Re-test on `main@3c527b0` (2026-09-18, after PR #83)

**Status: STILL-PRESENT.** PR #83 *does* touch this area -- `base_interpreter._handle_unhandled_event`
was rewritten for #79 (provenance-based exemption) and `interpreter.py` was
reworked for #43. Neither change reaches the receipt: the defer branch still
records no disposition on the pending receipt, and the receipt is still
resolved by the end-of-macrostep configuration/context diff. `Receipt` remains
`('state_ids', 'changed', 'error')` -- no field was added to carry the defer
disposition. **This finding still gates the order path.**
Repro re-run on `3c527b0` with the same interpreter and environment.

```
$ python repro/a2_confirm_deferred_receipt.py
receipt at defer time:
  changed = False
  error   = None
  states  = ['gate.closed']
  context = {'filled': 0}
  deferred_count = 1

after OPEN (replay):
  states  = ['gate.filled']
  context = {'filled': 1}

CONFIRMED: the receipt said 'no change, no error' for an event that
was neither dropped nor processed.

# Receipt shape is unchanged on 3c527b0: ('state_ids', 'changed', 'error').
# Side-by-side with a genuine no-op (a handled, action-less event):
#   deferred event  -> changed=False error=None
#   true no-op      -> changed=False error=None
# The two are byte-identical. `deferred_count` reads 0 at the caller's
# await point in both cases, so it is NOT a usable discriminator from
# the call site either.
```

See `../../23-verify-3c527b0-findings.md` for the full re-test table.
