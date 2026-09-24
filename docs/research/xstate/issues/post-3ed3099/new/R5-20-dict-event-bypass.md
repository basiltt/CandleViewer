---
r5: R5-20
title: "Semantics: dict-shaped event accepts arbitrary keys without InvalidEventError validation"
labels: [enhancement, severity/medium, area/validation]
severity: Medium
repro_script: repro/R5-20_dict-event-bypass.py
commit: 3ed3099
python: 3.13.7
verified: true
---

## Summary

`#113`'s hostile-input sweep against `send()` shows `InvalidEventError`
firing correctly for every non-`str`, non-`dict` shape (`None`, `123`,
`1.5`, `b"GO"`, `["GO"]`, `object()`, `True`, `nan`). The one gap in that
sweep is the mapping form: `send({"type": "GO"})` validates only that
`"type"` is present and is a non-empty `str` — every other key in the
mapping passes through unvalidated and the machine transitions normally.
This is arguably intended (dict events are a documented input form, not a
hostile shape by itself), but it means the mapping path is the sole input
class in the sweep with no validation surface beyond a single required
key, which matters directly to an adopter validating events at a trust
boundary.

## Environment

- Commit: `3ed3099096d15544e96c9d9458c21c2a30ef48e3` (`main`,
  `[Unreleased] — targeting 0.8.1`; `__version__` still reports `0.8.0`,
  so this build is identified by commit).
- Python: CPython 3.13.7
- OS: Windows 11 Pro 10.0.26200
- Editable install of the repo into a local venv; no library source
  modified.

## Minimal reproduction

```python
"""R5-20 repro: send() accepts a mapping like {"type": "GO"} without routing
any keys beyond "type" through InvalidEventError validation -- every other
hostile shape (None, 123, bytes, list, object(), bool, nan) raises correctly,
but a dict is accepted and transitions the machine.

Exits 1 while the defect is present (as far as documenting the gap), 0 once
InvalidEventError validates dict-shaped events beyond the "type" key too.
Stdlib + xstate_statemachine only.
"""
import sys

from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter
from xstate_statemachine.exceptions import InvalidEventError

CFG = {"id": "m", "initial": "a", "states": {"a": {"on": {"GO": "b"}}, "b": {}}}


def main() -> int:
    m = create_machine(CFG, logic=MachineLogic())

    hostile = [None, 123, 1.5, b"GO", ["GO"], object(), True, float("nan")]
    results = []
    for h in hostile:
        interp = SyncInterpreter(m).start()
        try:
            interp.send(h)
            results.append((repr(h), "NO ERROR RAISED"))
        except InvalidEventError:
            results.append((repr(h), "InvalidEventError OK"))
        except Exception as e:  # noqa: BLE001
            results.append((repr(h), f"UNCONTROLLED {type(e).__name__}"))

    # The mapping form: only "type" is validated; everything else passes.
    dict_interp = SyncInterpreter(m).start()
    dict_transitioned = False
    dict_raised = None
    try:
        dict_interp.send({"type": "GO"})
        dict_transitioned = "m.b" in dict_interp.current_state_ids
    except Exception as e:  # noqa: BLE001
        dict_raised = type(e).__name__

    print("OBSERVED (non-dict hostile shapes):")
    for h, r in results:
        print(f"  {h:20s} -> {r}")
    bad = [r for _, r in results if r != "InvalidEventError OK"]
    print(f"  BAD_COUNT (non-dict): {len(bad)}")
    print()
    print("OBSERVED (dict-shaped event):")
    print(f"  send({{'type': 'GO'}}) raised : {dict_raised}")
    print(f"  transitioned to m.b           : {dict_transitioned}")

    print("EXPECTED:")
    print("  every hostile shape either raises InvalidEventError, or (for the")
    print("  documented mapping form) the mapping's non-'type' keys are also")
    print("  validated as a payload dict -- the sweep should not have a single")
    print("  unvalidated input class")

    fail = len(bad) > 0 or (dict_raised is None and dict_transitioned)
    if fail:
        print("RESULT: FAIL - dict-shaped event bypasses InvalidEventError beyond 'type'")
        return 1
    print("RESULT: PASS")
    return 0


sys.exit(main())
```

## Observed behaviour

```
OBSERVED (non-dict hostile shapes):
  None                 -> InvalidEventError OK
  123                  -> InvalidEventError OK
  1.5                  -> InvalidEventError OK
  b'GO'                -> InvalidEventError OK
  ['GO']               -> InvalidEventError OK
  <object object at 0x00000157F9450AC0> -> InvalidEventError OK
  True                 -> InvalidEventError OK
  nan                  -> InvalidEventError OK
  BAD_COUNT (non-dict): 0

OBSERVED (dict-shaped event):
  send({'type': 'GO'}) raised : None
  transitioned to m.b           : True
EXPECTED:
  every hostile shape either raises InvalidEventError, or (for the
  documented mapping form) the mapping's non-'type' keys are also
  validated as a payload dict -- the sweep should not have a single
  unvalidated input class
RESULT: FAIL - dict-shaped event bypasses InvalidEventError beyond 'type'
```

## Expected behaviour

XState v5's own event object contract requires every event to be "an
object with a `type` property" (stately.ai/docs/transitions#event-object) —
it does not further constrain the remaining keys, so accepting an arbitrary
mapping is not itself a semantics violation. The library's own docstring
for `_prepare_event` (`base_interpreter.py:1877-1882`) documents
`InvalidEventError` as covering "a non-`str` `type`, a dict without `type`,
or an unsupported object" — the remaining-keys case is simply outside that
contract today, and this issue is recorded so the boundary is explicit
rather than assumed: an adopter validating untrusted input at `send()`
needs to know the mapping form's payload keys are not type-checked by the
library and must be validated by the caller (or the library should extend
`InvalidEventError` to cover, e.g., non-string keys or reserved keys
colliding with engine internals).

## Root cause analysis

- `base_interpreter.py:1888-1901` (`_prepare_event`) — for a `dict` input:
  checks `"type" not in data` (`:1891`) and `not isinstance(event_type, str)
  or not event_type` (`:1897`), both raising `InvalidEventError`. No
  further validation is applied to the remaining keys in `data`; they are
  passed straight through as the event's `payload`.
- Contrast with the `str` branch (`:1885-1886`) and the non-str/non-dict
  branch (unshown, further down), both of which are exhaustively type
  checked — the `dict` branch is the only one of the three input classes
  whose contents (beyond one required key) are unchecked.

## Impact

General: a boundary that validates events by relying solely on
`InvalidEventError` — the library's advertised hostile-input defense — will
not catch a malformed payload smuggled in via the mapping form (e.g. a
payload value that later breaks JSON serialization inside an action,
surfacing as a *different*, less legible error deep in a transition rather
than at the `send()` boundary).

Concrete order-management scenario: an OMS ingesting order events over a
message queue calls `send({"type": "ORDER_FILLED", **untrusted_payload})`
and relies on `except InvalidEventError` to reject malformed messages at
the boundary; a malformed `untrusted_payload` (e.g. non-JSON-serializable
values that later trip `SnapshotSerializationError` during persistence)
sails through `send()` uncaught and only surfaces later, off the intake
boundary, as a different and harder-to-attribute error.

## Proposed fix

Document explicitly, in `_prepare_event`'s docstring and in the public
`send()` docs, that the mapping form validates only `type`; payload keys
are the caller's responsibility. Optionally, extend `InvalidEventError` to
reject a mapping whose keys are not all `str` (mirroring the `type` check)
as a cheap, unambiguous strengthening that catches at least one class of
malformed payload without guessing at payload *semantics*, which are
necessarily domain-specific.

Compatibility: documentation-only change plus an optional additive
validation (non-str keys are already almost certainly a caller bug, not a
legitimate use) — should not break any currently-passing payloads.

## Acceptance criteria

- [ ] `repro/R5-20_dict-event-bypass.py` exits `0` (documents the sweep;
      passes once behavior is either fixed or the docstring/docs
      explicitly narrow the contract, whichever direction is chosen).
- [ ] `tests/test_events.py::test_dict_event_non_str_keys_raise_invalid_event_error`
      (if the optional strengthening is adopted).
- [ ] Docstring/docs update on `send()` and `_prepare_event()` making the
      mapping-form validation boundary explicit either way.

## Related

- Register source: R5-20, evidence
  `security/attack_invalid_event_hostile.py`, `triage-r5/t2_engine.py`.
- `#113` (`InvalidEventError` itself).
- Ride-along consideration alongside R5-17 (non-`str` event type via
  restore) — both sit on the same `type`-only validation boundary from two
  different call paths (`send()` here, `from_snapshot` there).

## Verification

- Date: 2026-09-19
- Python: CPython 3.13.7 (`.venv-main`)
- Commit: `3ed3099096d15544e96c9d9458c21c2a30ef48e3` (`main`, unreleased 0.8.1)
- Re-ran `repro/R5-20_dict-event-bypass.py` fresh: exit 1.
- Root-cause file:line citations checked against `src/xstate_statemachine`
  at this commit; all confirmed exact.
- Duplicates check: `gh issue list -R basiltt/xstate-statemachine --state all
  --limit 150 --search "<keyword>"` run for this finding's keywords; no
  round-4 issue (#102-#138, all CLOSED) covers this exact gap — #113 covers the non-dict hostile shapes and the dict form's 'type' key only, not the unvalidated-remaining-keys gap this issue documents.
