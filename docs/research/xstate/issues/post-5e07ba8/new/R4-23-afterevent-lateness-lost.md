---
r4: R4-23
title: "Bug: AfterEvent lateness telemetry (scheduled_for/fired_at) resets to 0.0 across a snapshot round-trip"
labels: [bug, severity/medium, area/timers, area/persistence, area/events]
severity: Medium
repro_script: repro/R4-23_afterevent_lateness_lost.py
commit: 5e07ba8
python: 3.13.7
verified: true
---
## Summary

`persist_event()` writes only `{"kind": "after", "type": ...}` for an
`AfterEvent`, dropping its `scheduled_for` and `fired_at` fields.
`restore_event()` then reconstructs both as `0.0` (the `AfterEvent`
default), so a restored timer event's lateness telemetry
(`lateness_ms = fired_at - scheduled_for`) reads as exactly `0.0` — an
**affirmative claim the timer fired precisely on schedule** — rather than
"unknown". Any lateness-alerting consumer reading a restored event stream
sees a false negative: a timer that actually fired 7.5 seconds late
appears perfectly healthy after a restart.

## Environment

- Commit: `5e07ba8` (xstate_statemachine 0.8.1 unreleased; `__version__` reports 0.8.0)
- Python: 3.13.7, Windows 11
- Editable install of the library under a project-local venv (`.venv-main`)

## Minimal reproduction

```python
# -*- coding: utf-8 -*-
"""R4-23: `AfterEvent` lateness telemetry (`scheduled_for` / `fired_at` /
`lateness_ms`) silently resets to 0.0 across a snapshot round-trip.
`persist_event()` writes only `{"kind", "type"}` for an `after` record;
`restore_event()` reconstructs both floats as 0.0. This is not "unknown"
telemetry -- it is an affirmative (and false) claim that the timer fired
exactly on schedule, which a restored lateness-alerting consumer cannot
distinguish from a genuinely on-time timer.

Standalone, derived from
probes/main-5e07ba8-final/r37_after_lateness_loss.py and
battle-5e07ba8/persistence/t3_probes.py (P5, probe_v2_roundtrip).

Exits 1 (defect present) if scheduled_for/fired_at/lateness_ms are lost
(reset to 0.0, not preserved / not representable as None) across
persist_event -> restore_event. Exits 0 once the v2 'after' record
preserves them (or represents "unavailable" as None rather than 0.0).
"""
from __future__ import annotations

from xstate_statemachine.events import AfterEvent, persist_event, restore_event


def main() -> int:
    ev = AfterEvent(
        type="after.5000.order.pending", scheduled_for=1000.0, fired_at=1007.5
    )
    original_lateness = getattr(ev, "lateness_ms", None)
    print(f"OBSERVED original: {ev} lateness_ms={original_lateness}")

    record = persist_event(ev)
    print(f"OBSERVED persisted record: {record}")

    restored = restore_event(record)
    restored_lateness = getattr(restored, "lateness_ms", None)
    print(f"OBSERVED restored: {restored} lateness_ms={restored_lateness}")

    print(
        "EXPECTED: scheduled_for/fired_at (and lateness_ms) survive the "
        "round-trip, or -- if genuinely unavailable -- restore as None "
        "(an explicit 'unknown'), never as 0.0 (an affirmative 'on time')"
    )

    lost = (restored.scheduled_for, restored.fired_at) != (
        ev.scheduled_for,
        ev.fired_at,
    )
    false_on_time = restored.scheduled_for == 0.0 and restored.fired_at == 0.0
    print(
        f"\nVERDICT: telemetry_lost={lost} "
        f"restored_as_false_on_time={false_on_time}"
    )
    return 1 if lost else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

## Observed behaviour

```
OBSERVED original: AfterEvent(type='after.5000.order.pending', scheduled_for=1000.0, fired_at=1007.5) lateness_ms=7500.0
OBSERVED persisted record: {'kind': 'after', 'type': 'after.5000.order.pending'}
OBSERVED restored: AfterEvent(type='after.5000.order.pending', scheduled_for=0.0, fired_at=0.0) lateness_ms=0.0
EXPECTED: scheduled_for/fired_at (and lateness_ms) survive the round-trip, or -- if genuinely unavailable -- restore as None (an explicit 'unknown'), never as 0.0 (an affirmative 'on time')

VERDICT: telemetry_lost=True restored_as_false_on_time=True
```
(exit code 1 — defect present)

## Expected behaviour

`persist_event`/`restore_event` already round-trip every other structured
field of every other engine event kind (`payload` for `event`/`system`,
`data`/`src` for `done`, `error`/`src` for `error`) — the v2 record format
exists specifically to "round-trip every engine event kind instead of
silently dropping the NamedTuple ones" (per the function's own
docstring). `AfterEvent`'s `scheduled_for`/`fired_at` fields are exactly
this kind of structured, NamedTuple-carried data and should be preserved
the same way `data`/`src` are for `DoneEvent`. Where a value is genuinely
unavailable, the field should restore as `None` (an honest "unknown"),
never as `0.0` (a specific, false, "delivered exactly on schedule"
claim).

## Root cause analysis

- `events.py:284-302` (`persist_event`) — the `if/elif` chain handles
  `event`/`system` (adds `payload`), `done` (adds `data`, `src`), `error`
  (adds `error`, `src`), but has **no branch for `kind == "after"`** —
  an `AfterEvent` record therefore only ever gets the two fields set
  unconditionally at the top: `{"kind": "after", "type": event.type}`.
- `events.py:305-325` (`restore_event`) — reconstructing an `AfterEvent`
  from a v2 record with no `scheduled_for`/`fired_at` keys falls back to
  the `AfterEvent` NamedTuple's own defaults, which are `0.0` for both
  fields (per the class definition around `events.py:363` onward),
  producing `lateness_ms == 0.0`.
- This is currently masked in practice by R4-11 (fired `AfterEvent`s are
  not persisted to the pending/deferred lists at all in the common path),
  so the loss is invisible until R4-11 is fixed — at which point this
  becomes a live false-negative in lateness telemetry rather than a
  theoretical one.

## Impact

For general users building lateness/SLA alerting on top of restored event
history (a natural use of a library that exposes `lateness_ms` as a
first-class field on the event type), a restart or crash-recovery cycle
silently converts every "this timer fired late" data point into "this
timer fired exactly on time" — the opposite of the truth, and worse than
simply losing the data, because a missing/`None` value is at least
auditable as "unknown" while `0.0` reads as a specific, confident
measurement. In the adopting project's order-management scenario, a
restored order interpreter's timeout/escalation timers (e.g. an
order-acknowledgement deadline) would report perfect timeliness after
every process restart regardless of how late they actually fired,
defeating any alerting or SLA-compliance reporting built on that
telemetry across restarts — precisely the long-running-service window
where restarts are common and where this telemetry matters most.

## Proposed fix

Add an `elif kind == "after":` branch to `persist_event()` that writes
`rec["scheduled_for"] = event.scheduled_for` and `rec["fired_at"] =
event.fired_at`. In `restore_event()`, read these back explicitly when
present: `record.get("scheduled_for")`/`record.get("fired_at")`, and if
genuinely absent (an old v1-style record with no such keys), construct
the `AfterEvent` with `scheduled_for=None, fired_at=None` rather than
letting it fall through to the `0.0` default, so "unknown" is
representable and distinguishable from "measured and exactly zero
lateness". This requires `AfterEvent`'s fields to accept `Optional[float]`
(they may already be untyped/implicitly `Any` as a `NamedTuple`) and
`lateness_ms` to handle `None` inputs by returning `None` rather than
raising or computing a bogus value.

## Acceptance criteria

- [ ] `persist_event(AfterEvent(...))` includes `scheduled_for` and
      `fired_at` in the record.
- [ ] `restore_event(record)` reconstructs the original
      `scheduled_for`/`fired_at` values exactly.
- [ ] A v1-style record with no `scheduled_for`/`fired_at` keys restores
      them as `None`, not `0.0`.
- [ ] `tests/test_events_persistence.py::test_after_event_roundtrips_lateness_fields`
- [ ] `tests/test_events_persistence.py::test_after_event_missing_lateness_fields_restore_as_none`
- [ ] `repro/R4-23_afterevent_lateness_lost.py` exits 0

## Related

- Register source ids: `D-persistence-7`, `L-1`
- Currently masked by R4-11 (fired `AfterEvent`s are not persisted at
  all); fixing R4-11 without also fixing this turns a masked bug into a
  live false-negative in lateness telemetry
- Merges what the register lists as two separate source findings
  (`D-persistence-7` and `L-1`) into a single root cause in `events.py`

## Verification

- Date: 2026-09-19; Python 3.13.7; commit `5e07ba8`.
- Re-ran `repro/R4-23_afterevent_lateness_lost.py` in a fresh process
  (60s cap): output matched the Observed block verbatim
  (`persisted record: {'kind': 'after', 'type': ...}`, restored
  `scheduled_for=0.0 fired_at=0.0 lateness_ms=0.0`); exit code `1`.
- Confirmed `src/xstate_statemachine/events.py`: `persist_event()`'s
  `if/elif` chain has branches for `event`/`system`/`done`/`error` but
  none for `kind == "after"`; `restore_event()` has a `kind == "after"`
  branch (line 330) that constructs `AfterEvent` with no
  `scheduled_for`/`fired_at` override, falling back to the dataclass
  defaults `scheduled_for: float = 0.0` / `fired_at: float = 0.0` — line
  citations match the draft.
- No external XState/SCXML claim requiring a fetch (this is a Python
  library persistence-format gap in its own v2 event-record round-trip
  contract, not an XState/SCXML spec question).
- Searched `gh issue list -R basiltt/xstate-statemachine --state all
  --limit 120 --search "lateness"`: no matching issue (only unrelated
  timer perf/docs issues #48/#56 surfaced); no duplicate found.
- No project name/label leakage found in the file.
