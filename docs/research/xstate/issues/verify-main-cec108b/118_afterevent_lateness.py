"""Verify #118 on main@cec108b: AfterEvent lateness telemetry (scheduled_for/
fired_at/lateness_ms) survives persist_event/restore_event round-trip, and a
v1-style record (no keys) restores as None, not 0.0.

Exit 0 iff all acceptance criteria + CHANGELOG claim hold.
"""
from __future__ import annotations
import sys as _xs_sys  # noqa: E402
from pathlib import Path as _XsPath  # noqa: E402
_xs_sys.path.insert(0, str(_XsPath(__file__).resolve().parents[2] / "gate"))
from _paths import REPO_ROOT as _REPO, XSTATE_SRC as _XS, upstream_main_python as _xs_main_py  # noqa: E402,F401

import sys

sys.path.insert(
    0, str(_XS / 'src')
)

from xstate_statemachine.events import AfterEvent, persist_event, restore_event  # noqa: E402

failures = []


def check(name, cond):
    print(f"[{'OK' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


def main() -> int:
    ev = AfterEvent(type="after.5000.order.pending", scheduled_for=1000.0, fired_at=1007.5)
    rec = persist_event(ev)
    check("persist_event includes scheduled_for", rec.get("scheduled_for") == 1000.0)
    check("persist_event includes fired_at", rec.get("fired_at") == 1007.5)

    back = restore_event(rec)
    check(
        "restore_event reconstructs exact values",
        back.scheduled_for == 1000.0 and back.fired_at == 1007.5,
    )
    check("lateness_ms correct", back.lateness_ms == 7500.0)

    v1_style = {"kind": "after", "type": "after.5000.order.pending"}
    restored_v1 = restore_event(v1_style)
    check(
        "v1-style record (no keys) restores as None, not 0.0",
        restored_v1.scheduled_for is None and restored_v1.fired_at is None,
    )
    check("lateness_ms is None when unknown", restored_v1.lateness_ms is None)

    return 0 if not failures else 1


if __name__ == "__main__":
    rc = main()
    print(f"\nRESULT: {'PASS' if rc == 0 else 'FAIL'} ({len(failures)} failing)")
    sys.exit(rc)
