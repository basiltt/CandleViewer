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
