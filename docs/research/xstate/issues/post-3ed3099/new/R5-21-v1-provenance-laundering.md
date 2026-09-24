---
r5: R5-21
title: "Bug: v1 snapshot restore re-derives provenance from event name, laundering user events into system events"
labels: [bug, severity/low, area/persistence]
severity: Low
repro_script: repro/R5-21_v1-provenance-laundering.py
commit: 3ed3099
python: 3.13.7
verified: true
---

## Summary

`restore_event()` handles legacy ("v1") persisted records that predate the
`kind` discriminator added for `#86`/`#87` provenance tracking. For those
records, provenance is re-derived by checking whether the event's `type`
string starts with an engine prefix (`ENGINE_EVENT_SHAPES`) — so a
genuinely user-authored event whose name happens to collide with an engine
shape (e.g. a user event literally named `"after.hours"` for a
business-hours check, or `"xstate.custom"`) restores as
`Event(system=True)`, indistinguishable from a real engine-minted event.
This is a real gap in the restore path but is largely closed going forward:
`#79` closes the intake path for *new* events (new records always carry
`kind`), so exposure requires an old, pre-0.8.1 persisted blob containing a
user event with an engine-shaped name.

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
"""R5-21 repro: restore_event() re-derives provenance from the event NAME for
a v1 (no "kind") record, laundering an engine-shaped user event name (e.g.
"after.hours" or "xstate.custom") into Event(system=True) on restore, even
though it was originally ordinary user traffic.

Exits 1 while the defect is present, 0 once fixed.
Stdlib + xstate_statemachine only.
"""
import sys

from xstate_statemachine.events import restore_event

V1_RECORDS = [
    # A user chose this event name; it happens to start with an engine
    # prefix ("after."). No `kind` key exists in a v1 record.
    {"type": "after.hours", "payload": {"note": "user event, not a timer"}},
    {"type": "xstate.custom", "payload": {"note": "user event, not a system event"}},
    # Control: a genuine done event name, still correctly classed "event".
    {"type": "done.review", "payload": {"note": "user event named like a done event"}},
]


def main() -> int:
    print("OBSERVED:")
    laundered = []
    for rec in V1_RECORDS:
        restored = restore_event(rec)
        system = getattr(restored, "system", None)
        print(f"  v1 record type={rec['type']!r:20s} -> Event(system={system})")
        if system is True:
            laundered.append(rec["type"])

    print("EXPECTED:")
    print("  a v1 record for a genuine USER event must never restore with")
    print("  system=True purely because its name happens to share an engine")
    print("  prefix -- provenance should default to 'event' for v1 records")
    print("  whose origin cannot be proven, not 'system' by name-sniffing")

    if laundered:
        print(f"RESULT: FAIL - laundered to system=True: {laundered}")
        return 1
    print("RESULT: PASS")
    return 0


sys.exit(main())
```

## Observed behaviour

```
OBSERVED:
  v1 record type='after.hours'        -> Event(system=True)
  v1 record type='xstate.custom'      -> Event(system=True)
  v1 record type='done.review'        -> Event(system=False)
EXPECTED:
  a v1 record for a genuine USER event must never restore with
  system=True purely because its name happens to share an engine
  prefix -- provenance should default to 'event' for v1 records
  whose origin cannot be proven, not 'system' by name-sniffing
RESULT: FAIL - laundered to system=True: ['after.hours', 'xstate.custom']
```

Note the asymmetry with the third, control row: `"done.review"` is *not*
laundered because `ENGINE_EVENT_SHAPES` (the prefix set checked) does not
include the bare `"done."` prefix used for this check — only `after.` /
`xstate.` style shapes are — which shows the laundering is a real, narrow,
name-collision effect and not a blanket "everything gets system=True" bug.

## Expected behaviour

The library's own `Event.system` property docstring
(`events.py:116-127`) states the flag marks provenance "user code cannot
obtain by name" for live traffic — i.e., the whole design point of
`system` is that it must not be derivable from the event's name alone for
ordinary user-authored events. Re-deriving it from the name at restore time
for legacy records directly contradicts that design invariant, even though
it is the only signal available at that specific boundary. XState v5's own
implementation reserves the `xstate.*` prefix for its own internal action/
event constants (e.g. `xstate.raise`, `xstate.send`, `xstate.pure`,
`xstate.log`, `xstate.start` — github.com/statelyai/xstate,
`packages/core/src/types.ts`), so a *conforming* engine never mints a
user-facing event under that prefix; the residual risk this issue documents
is specifically a user choosing a colliding name, not the engine's own
usage. Given that, the safer default for an unproven legacy record is to
trust the recorded *shape*
(`Event` vs `DoneEvent`/`ErrorEvent`/`AfterEvent`, which v1 records do
distinguish via their other fields) rather than sniff the `type` string.

## Root cause analysis

- `events.py:357-391` (`restore_event`) — for `kind is None` (a v1
  record), line `:369`:
  ```python
  kind = "system" if etype.startswith(ENGINE_EVENT_SHAPES) else "event"
  ```
  This re-derives `kind` (and therefore `Event.system`) from the `type`
  string alone. `ENGINE_EVENT_SHAPES` (defined near `events.py:57`) is a
  tuple of prefixes the engine mints, but nothing prevents *user* code from
  choosing a `type` string that happens to share one of those prefixes —
  there is no reservation/validation on `send()`'s `event_type` guarding
  against user-chosen names colliding with engine shapes.
- `#79` (referenced in the same docstring, `:363`) closes the *intake*
  path going forward — new persisted records always carry `kind`
  (`persist_event`, `events.py:313-342`, always sets `rec["kind"] =
  event_kind(event)`) — so this is a residual-only gap affecting blobs
  written before that fix landed.

## Impact

General: restoring a pre-0.8.1 persisted blob can misclassify a stored
user event as system-provenance, which matters anywhere `Event.system`
gates behavior — e.g. a wildcard handler or logging filter that
special-cases system events, or future code that trusts `system=True` as a
security boundary (per the property's own docstring intent).

Concrete order-management scenario: an OMS migrating from a pre-0.8.1
version restores an archived order-workflow snapshot containing a
historical user event named `"after.hours.override"` (a real business
event, an operator's manual override submitted outside business hours);
on restore it is reclassified `system=True`, and any restore-time logic
that trusts `system` events differently (e.g. skips re-validation, or
routes them past an audit filter meant only for user traffic) would
mishandle it.

## Proposed fix

Arguably unfixable as stated without more information — the remedy is an
explicit, one-time migration path: on first load of a v1 record, default
`kind` to `"event"` (the strictly safer default — under-classifying a
handful of true engine records as user traffic is lower risk than
over-classifying user traffic as system) unless a stronger signal exists,
and document that pre-0.8.1 archives containing genuinely engine-shaped
records restored *before* this change relied on the name heuristic and
should be re-persisted (which re-stamps `kind` correctly) at the next
opportunity after upgrading.

Compatibility: changes restore-time classification for any v1 blob whose
`type` collides with `ENGINE_EVENT_SHAPES` — call out explicitly in the
changelog as a behavior change for legacy-blob restores, alongside the
existing `#79` migration note.

## Acceptance criteria

- [ ] `repro/R5-21_v1-provenance-laundering.py` exits `0`.
- [ ] `tests/test_events.py::test_v1_record_defaults_to_user_event_provenance`
      — a v1 record with an engine-shaped `type` restores with
      `system=False` by default.
- [ ] `tests/test_events.py::test_v1_record_engine_shape_migration_documented`
      — changelog/docs note pointing pre-0.8.1 adopters at re-persisting
      archives to correct classification.
- [ ] Changelog entry noting the restore-time default change for v1
      records.

## Related

- Register source: R5-21, evidence
  `persistence/t4_receipts_provenance.py::P12`.
- `#79` (closes the intake path for new events — this issue is the
  residual v1-blob-only gap left after that fix).
- `#86` (introduced the `kind` discriminator this issue's fallback path
  predates).

## Verification

- Date: 2026-09-19
- Python: CPython 3.13.7 (`.venv-main`)
- Commit: `3ed3099096d15544e96c9d9458c21c2a30ef48e3` (`main`, unreleased 0.8.1)
- Re-ran `repro/R5-21_v1-provenance-laundering.py` fresh: exit 1.
- Root-cause file:line citations checked against `src/xstate_statemachine`
  at this commit; all confirmed exact.
- Duplicates check: `gh issue list -R basiltt/xstate-statemachine --state all
  --limit 150 --search "<keyword>"` run for this finding's keywords; no
  round-4 issue (#102-#138, all CLOSED) covers this exact gap — #79/#86 close the forward intake path but neither addresses the residual v1-record name-sniffing fallback this issue targets.
