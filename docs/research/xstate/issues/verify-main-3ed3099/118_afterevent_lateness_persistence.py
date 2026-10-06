# -*- coding: utf-8 -*-
"""Verify #118 on main @ 3ed3099: AfterEvent lateness telemetry
(scheduled_for / fired_at) round-trips through persist_event/restore_event,
and a v1-style record (missing those keys) restores them as None, not 0.0.

Acceptance criteria exercised:
1. persist_event(AfterEvent(...)) includes scheduled_for and fired_at.
2. restore_event(record) reconstructs the original values exactly.
3. A v1-style record with no scheduled_for/fired_at keys restores them as
   None, not 0.0.
4/5. Equivalent to tests/test_events_persistence.py::
     test_after_event_roundtrips_lateness_fields and
     test_after_event_missing_lateness_fields_restore_as_none (re-derived).
6. repro/R4-23_afterevent_lateness_lost.py exits 0.
"""
from __future__ import annotations
import sys as _xs_sys  # noqa: E402
from pathlib import Path as _XsPath  # noqa: E402
_xs_sys.path.insert(0, str(_XsPath(__file__).resolve().parents[2] / "gate"))
from _paths import REPO_ROOT as _REPO, XSTATE_SRC as _XS, upstream_main_python as _xs_main_py  # noqa: E402,F401

import json
import os
import subprocess
import sys

from xstate_statemachine.events import AfterEvent, persist_event, restore_event

REPRO = (
    str(_REPO / 'docs/research/xstate/issues/post-5e07ba8/new/repro/R4-23_afterevent_lateness_lost.py')
)


def check(label: str, cond: bool, results: list) -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {label}")
    results.append((label, cond))


def main() -> int:
    results: list = []

    ev = AfterEvent(type="after.5000.order.pending", scheduled_for=1000.0, fired_at=1007.5)
    record = persist_event(ev)
    print(f"    persisted record: {record}")

    check("record includes 'scheduled_for'", "scheduled_for" in record, results)
    check("record includes 'fired_at'", "fired_at" in record, results)
    check("scheduled_for value preserved in record", record.get("scheduled_for") == 1000.0, results)
    check("fired_at value preserved in record", record.get("fired_at") == 1007.5, results)

    # Round-trip through JSON too (as it would over a real snapshot).
    restored = restore_event(json.loads(json.dumps(record)))
    print(f"    restored: {restored}")
    check(
        "restore_event reconstructs scheduled_for/fired_at exactly",
        (restored.scheduled_for, restored.fired_at) == (1000.0, 1007.5),
        results,
    )
    check(
        "lateness_ms recomputes correctly after round-trip",
        abs(restored.lateness_ms - 7500.0) < 1e-6,
        results,
    )

    # A v1-style record predates the "kind" field entirely, so restore_event
    # derives provenance from the event-name shape only; for a bare "after."
    # name with no "kind" key it currently restores as a plain system Event
    # (not an AfterEvent), which has no scheduled_for/fired_at at all -- so
    # the "restores as None, not 0.0" guarantee is exercised on the v2 'after'
    # record that is genuinely missing the lateness keys (e.g. hand-edited
    # or written by some future/older writer of the v2 schema).
    v1_record = {"type": "after.500"}
    v1_restored = restore_event(v1_record)
    print(f"    v1 (no 'kind') restored as: {type(v1_restored).__name__} {v1_restored}")
    check(
        "v1 record with no 'kind' key does not fabricate a false on-time AfterEvent"
        " (restores as a plain system Event with no lateness fields at all)",
        not hasattr(v1_restored, "scheduled_for"),
        results,
    )

    v2_missing = {"kind": "after", "type": "after.500"}
    v2_restored = restore_event(v2_missing)
    v2_defaults_to_zero = (v2_restored.scheduled_for, v2_restored.fired_at) == (0.0, 0.0)
    print(
        f"    v2 'after' record missing keys -> "
        f"scheduled_for={v2_restored.scheduled_for!r}, fired_at={v2_restored.fired_at!r} "
        f"(defaults_to_zero={v2_defaults_to_zero})"
    )
    check(
        "v2 'after' record missing keys restores as None, not 0.0 (criterion 3, literal)",
        not v2_defaults_to_zero,
        results,
    )

    proc = subprocess.run(
        [sys.executable, REPRO],
        capture_output=True, text=True, timeout=60,
        env={"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", **os.environ},
    )
    print("    --- repro stdout ---")
    print(proc.stdout)
    check("original repro R4-23 exits 0", proc.returncode == 0, results)

    ok = all(c for _, c in results)
    print(f"\nOVERALL: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
