---
r4: R4-40
title: "Docs: engine-event provenance does not survive deepcopy or pickle"
labels: [documentation, severity/low, area/events]
severity: Low
repro_script: repro/R4-40_provenance_deepcopy_pickle.py
commit: 5e07ba8
python: 3.13.7
verified: true
---

## Summary

`system_event()` marks an `Event` as engine-originated using an
engine-private identity sentinel (`_ENGINE_MARK = object()`), and
`is_system_event()` checks for it with an `is` comparison. `copy.copy()`
preserves this correctly (a shallow copy keeps a reference to the same
sentinel object), but `copy.deepcopy()` and `pickle` both reconstruct a
new object for the sentinel, so identity comparison fails silently and
provenance is lost — with no exception, no warning, just a downgraded
event. This is inherent to the chosen identity-based mechanism rather than
a slip, and the snapshot codec (`kind`, via `persist_event`/`restore_event`)
is the intended cross-process path — but the asymmetry between `copy.copy`
(preserves) and `copy.deepcopy` (loses) is surprising, and a
`multiprocessing` hand-off of an engine event silently demotes it to a
"user event" for consumers on the other side of that boundary.

## Environment

- Commit: 5e07ba8 (unreleased 0.8.1; `__version__` reports 0.8.0)
- Python: 3.13.7
- OS: Windows 11
- Editable install via `.venv-main`

## Current behaviour and why it is insufficient

```python
"""R4-40: engine provenance does not survive deepcopy or pickle.

system_event() marks an Event as engine-originated via an identity
sentinel (`_ENGINE_MARK = object()`, compared with `is`). copy.copy()
preserves this (shallow copy keeps the same sentinel object by
reference), but copy.deepcopy() and pickle both reconstruct a new
sentinel object, so identity comparison fails and provenance is silently
lost -- even though the codebase deep-copies event payloads in several
places, and a multiprocessing hand-off of an engine event relies on
pickle.

Exits 1 (defect present) while deepcopy or pickle loses provenance.
Exits 0 once provenance survives both (e.g. via __deepcopy__ / __reduce__).
"""
import copy
import pickle
import sys

from xstate_statemachine.events import Event, is_system_event, system_event


def main() -> int:
    ev = system_event("xstate.init")

    original_ok = is_system_event(ev)
    copy_ok = is_system_event(copy.copy(ev))
    deepcopy_ok = is_system_event(copy.deepcopy(ev))
    try:
        pickle_ok = is_system_event(pickle.loads(pickle.dumps(ev)))
        pickle_error = None
    except Exception as exc:  # noqa: BLE001
        pickle_ok = False
        pickle_error = f"{type(exc).__name__}: {exc}"

    print("OBSERVED:")
    print(f"  is_system_event(original)      = {original_ok}")
    print(f"  is_system_event(copy.copy)     = {copy_ok}")
    print(f"  is_system_event(copy.deepcopy) = {deepcopy_ok}")
    if pickle_error:
        print(f"  is_system_event(pickle roundtrip) = FAILED: {pickle_error}")
    else:
        print(f"  is_system_event(pickle roundtrip) = {pickle_ok}")

    print(
        "\nEXPECTED: provenance (is_system_event) survives copy.copy, "
        "copy.deepcopy, and a pickle round-trip -- an engine event should "
        "still read as engine-originated after crossing a process boundary "
        "or being deep-copied"
    )

    defect_present = not (original_ok and copy_ok and deepcopy_ok and pickle_ok)
    if defect_present:
        print("\nRESULT: provenance lost across deepcopy/pickle -- defect present")
        return 1
    else:
        print("\nRESULT: provenance preserved -- fixed")
        return 0


if __name__ == "__main__":
    sys.exit(main())
```

## Observed behaviour

```
OBSERVED:
  is_system_event(original)      = True
  is_system_event(copy.copy)     = True
  is_system_event(copy.deepcopy) = False
  is_system_event(pickle roundtrip) = False

EXPECTED: provenance (is_system_event) survives copy.copy, copy.deepcopy, and a pickle round-trip -- an engine event should still read as engine-originated after crossing a process boundary or being deep-copied

RESULT: provenance lost across deepcopy/pickle -- defect present
```

## Expected behaviour

The library documents (per its own changelog/comments, see
`events.py:114-120`) that provenance is a deliberate security/correctness
mechanism — introduced specifically so user code cannot forge
engine-status and bypass `strict`, `onUnhandled`, and the `"*"` matcher.
A mechanism whose entire purpose is "this property must not be forgeable
or silently lost" should either survive the standard Python object-copying
protocols that the rest of the codebase already relies on for event
payloads, or the boundary at which it does *not* survive must be
explicitly documented so integrators do not assume it is safe.

## Root cause analysis

`src/xstate_statemachine/events.py:240` defines the sentinel:

```python
_ENGINE_MARK: Any = object()
```

and `is_system_event` (`events.py:243-253`) checks
`event._provenance is _ENGINE_MARK` — an identity check against this
specific in-process object. `Event` is a frozen dataclass with no custom
`__deepcopy__`, `__reduce__`, `__getstate__`/`__setstate__`, so:

- `copy.copy()` performs a shallow copy that keeps the same `_provenance`
  reference — provenance survives by accident of implementation, not by
  design.
- `copy.deepcopy()` recursively copies `_provenance` (an `object()`
  instance, which deepcopies to a *new* `object()` since it has no special
  deepcopy behavior) — the new object fails the `is` check.
- `pickle` serializes and reconstructs `Event`, but `object()` instances
  are not meaningfully picklable/restorable to the *same* identity —
  deserializing produces a new object that also fails the `is` check
  (or the whole pickle can fail depending on protocol, per the "FAILED"
  branch this repro guards for).

By construction, an identity sentinel cannot cross a process boundary or
survive object reconstruction — this is inherent to the mechanism, not a
one-off bug — but the `copy.copy`-preserves / `copy.deepcopy`-loses
asymmetry is undocumented and easy to trip over, especially since the
codebase deep-copies event payloads in several other places.

## Impact

For general users, any code path that deep-copies an `Event` (e.g. to hand
a mutable-payload event to multiple consumers safely) or moves one across
a `multiprocessing` boundary silently downgrades an engine-originated event
to indistinguishable-from-user-event status, which is exactly the class of
problem provenance was introduced to prevent (R4-08's consequence: a
`strict`/`onUnhandled`/`"*"` decision computed against the demoted event
would be wrong). For the adopting project's order-management scenario, a
worker-pool architecture that hands snapshot-adjacent event objects to a
`multiprocessing.Pool` for parallel audit processing would see every
system event silently reclassified as a user event on the far side — the
per-event dispatch decision (e.g. whether to persist it as a business
event) would be wrong for every engine-originated event, with no error to
signal the misclassification. Severity is Low because this is a
documented-limitation item (once documented) rather than an in-process
bug with a clean fix, and the snapshot codec (`persist_event`/
`restore_event`, driven by `event_kind`) is the already-existing correct
path for crossing a process/persistence boundary.

## Proposed API/text

Preferred: implement `Event.__deepcopy__` and `Event.__reduce__` (or
`__getstate__`/`__setstate__`) so that a deep-copied or pickled `Event`
re-derives its `_provenance` via the same engine-mark mechanism rather
than losing it — e.g. `__reduce__` can encode "this was a system event"
as a boolean flag reconstructed through `system_event()`'s own private
path on unpickling, keeping the anti-forgery property intact (a plain
user `Event.__reduce__` never sets that flag, so the identity sentinel
still cannot be spoofed by hand-constructing a payload).

Alternative (cheaper for 0.8.1): explicitly document the boundary — add a
note to `is_system_event`'s and `system_event`'s docstrings, and to any
provenance guide page created for R4-39, stating that `copy.deepcopy` and
`pickle` do not preserve provenance and that `persist_event`/
`restore_event` (the snapshot codec) is the supported way to carry an
event's provenance across a process or persistence boundary.

## Acceptance criteria

- [ ] Either `Event.__deepcopy__`/`__reduce__` is implemented so provenance survives `copy.deepcopy` and `pickle`, or the docstrings of `is_system_event`/`system_event` (and any R4-39 guide page) explicitly document that it does not, and point at `persist_event`/`restore_event` as the supported alternative.
- [ ] `tests/test_events.py::test_provenance_deepcopy_pickle_behavior` (new) pins down the chosen behavior (either "preserved" or "documented as lost, with a `persist_event` example alongside it").
- [ ] `repro/R4-40_provenance_deepcopy_pickle.py` exits 0 (if fixed) or is updated to assert the documented behavior explicitly (if the doc-only route is taken).

## Related

- Register source: `probes/main-5e07ba8/r1_provenance_copy.py`.
- Register row: R4-40 in `30-r4-findings-register.md`.
- Root cause file: `events.py:240` (`_ENGINE_MARK`), `events.py:253` (`system_event`).
- Kept separate from R4-08 (`_detach`'s `dataclasses.replace`, an in-process bug with a real fix) per the register's disposition: this is the deepcopy/pickle half of the same underlying provenance-audit theme, but a documented-limitation item rather than a fixable in-process bug.
- The register's disposition section suggests R4-08, R4-09 (refuted, skipped here) and R4-40 could be filed as one issue given the shared root theme ("provenance was not audited across a boundary that reconstructs an Event"); this issue is filed separately per this task's per-row instructions, but a maintainer doing the systematic audit the register recommends should read it alongside R4-08.

## Verification

- Date: 2026-09-19
- Python: 3.13.7 (`.venv-main`)
- Commit: 5e07ba8 (unreleased 0.8.1; `__version__` reports 0.8.0)
- Ran `repro/R4-40_provenance_deepcopy_pickle.py` in a fresh process: exit code 1, output matches the Observed section (`copy.copy` preserves provenance, `copy.deepcopy` and pickle round-trip both lose it).
- Confirmed root cause: `src/xstate_statemachine/events.py` defines `_ENGINE_MARK: Any = object()` at line 239 (register cites 240, off by one) and `is_system_event`'s identity check `event._provenance is _ENGINE_MARK` at line ~253 (function body spans 243-253). `Event` is a frozen dataclass with no `__deepcopy__`/`__reduce__`/`__getstate__`, so `object()`-based identity cannot survive deepcopy or pickle reconstruction — matches the narrative exactly.
- No external XState/SCXML claim to check (this is a Python-object-identity/serialization limitation specific to this library's implementation, not an XState/SCXML semantics claim).
- Checked for duplicates: `gh issue list -R basiltt/xstate-statemachine --state all --search "deepcopy pickle event"` returns no results. No duplicate found.
- No project name/label leakage found in the file.
- Status: reproducible, defect confirmed present.
