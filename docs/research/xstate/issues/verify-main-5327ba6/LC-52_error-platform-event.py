"""Verification of GH#80 (LC label: LC-52) on main @ 5327ba6.

Issue: `error.platform.*` events are still delivered as a `DoneEvent` whose
`.data` carries the exception -- there is no dedicated error-event type, so
a consumer must string-match `event.type` for the `error.` prefix to tell
"service succeeded with output" from "service failed".

Acceptance criteria (from GH#80):
  1. `error.platform.*` events are instances of a dedicated error event class
     exposing `.error`.
  2. `DoneEvent` is never used for failure delivery.
  3. Test: tests/test_events.py::test_service_failure_delivers_error_event
  4. The repro script in the issue body exits 0.

Per the task's "need": CHECK CHANGELOG for an ErrorEvent for error.platform.*.
If absent, classify NOT-FIXED honestly.

Exits 0 only if ALL criteria pass.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

RESULTS: dict[str, tuple[bool, str]] = {}


def record(name: str, ok: bool, detail: str) -> None:
    RESULTS[name] = (ok, detail)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")


def criterion_changelog_mentions_errorevent() -> None:
    changelog = Path(
        "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/"
        "xstate-statemachine/CHANGELOG.md"
    )
    text = changelog.read_text(encoding="utf-8")
    ok = "ErrorEvent" in text
    record(
        "need_changelog_mentions_ErrorEvent",
        ok,
        "found 'ErrorEvent' in [Unreleased] CHANGELOG" if ok else "NOT mentioned anywhere in CHANGELOG.md",
    )


def criterion_errorevent_class_exists() -> None:
    try:
        from xstate_statemachine.events import ErrorEvent  # type: ignore

        ok = True
        detail = f"xstate_statemachine.events.ErrorEvent exists: {ErrorEvent!r}"
    except ImportError:
        try:
            from xstate_statemachine import ErrorEvent  # type: ignore

            ok = True
            detail = f"xstate_statemachine.ErrorEvent exists: {ErrorEvent!r}"
        except ImportError as exc:
            ok = False
            detail = f"ImportError: no ErrorEvent class in events.py or top-level package ({exc})"
    record("criterion_1_dedicated_ErrorEvent_class_exists", ok, detail)


async def criterion_runtime_behaviour() -> tuple[str, object]:
    """Reproduce the issue body's exact script and inspect the delivered
    event's runtime type for an error.platform.* event."""
    from xstate_statemachine import create_machine, Interpreter, MachineLogic

    async def boom(interp, ctx, event):
        raise RuntimeError("venue rejected")

    m = create_machine(
        {
            "id": "m",
            "initial": "a",
            "states": {
                "a": {"invoke": {"src": "boom", "onError": {"target": "failed"}}},
                "failed": {},
            },
        },
        logic=MachineLogic(services={"boom": boom}),
    )
    seen = []

    class P:
        def on_event_received(self, interp, event):
            seen.append(event)

    i = Interpreter(m).use(P())
    await i.start()
    await asyncio.sleep(0.05)
    await i.stop()

    error_events = [
        e for e in seen if str(getattr(e, "type", "")).startswith("error.")
    ]
    if not error_events:
        return "NO_ERROR_EVENT_OBSERVED", None
    ev = error_events[0]
    return type(ev).__name__, ev


def criterion_tests_present() -> None:
    tests_dir = Path(
        "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/"
        "xstate-statemachine/tests"
    )
    combined = ""
    for f in tests_dir.glob("*.py"):
        combined += f.read_text(encoding="utf-8")
    ok = "test_service_failure_delivers_error_event" in combined
    record(
        "criterion_3_test_added",
        ok,
        "found test_service_failure_delivers_error_event"
        if ok
        else "test_service_failure_delivers_error_event NOT found in any tests/*.py",
    )


def criterion_original_repro() -> None:
    """Run the exact repro from the issue body as a subprocess so its
    SystemExit code is captured cleanly."""
    script = '''
import asyncio
from xstate_statemachine import create_machine, Interpreter, MachineLogic

async def boom(interp, ctx, event):
    raise RuntimeError("venue rejected")

m = create_machine(
    {"id": "m", "initial": "a",
     "states": {"a": {"invoke": {"src": "boom", "onError": {"target": "failed"}}},
                "failed": {}}},
    logic=MachineLogic(services={"boom": boom}),
)
seen = []
class P:
    def on_event_received(self, interp, event): seen.append(event)
i = Interpreter(m).use(P())
async def main():
    await i.start(); await asyncio.sleep(0.05); await i.stop()
    ev = [e for e in seen if str(getattr(e, "type", "")).startswith("error.")][0]
    print("OBSERVED type name :", type(ev).__name__)
    print("OBSERVED .type     :", ev.type)
    print("EXPECTED           : a dedicated ErrorEvent (or `error` attribute), not DoneEvent")
    raise SystemExit(1 if type(ev).__name__ == "DoneEvent" else 0)
asyncio.run(main())
'''
    py = "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/.venv-main/Scripts/python"
    import os

    proc = subprocess.run(
        [py, "-c", script],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
    )
    print("--- issue-body repro stdout ---")
    print(proc.stdout)
    if proc.stderr:
        print("--- issue-body repro stderr ---")
        print(proc.stderr)
    record(
        "criterion_4_issue_body_repro_exits_0",
        proc.returncode == 0,
        f"exit code={proc.returncode}",
    )


def main() -> int:
    criterion_changelog_mentions_errorevent()
    criterion_errorevent_class_exists()

    type_name, ev = asyncio.run(criterion_runtime_behaviour())
    is_done_event = type_name == "DoneEvent"
    record(
        "criterion_2_DoneEvent_not_used_for_failure",
        not is_done_event and type_name != "NO_ERROR_EVENT_OBSERVED",
        f"error.platform.* event runtime type observed = {type_name!r}"
        + (f", event={ev!r}" if ev is not None else ""),
    )
    has_error_attr = ev is not None and hasattr(ev, "error")
    record(
        "criterion_1b_delivered_event_exposes_dot_error",
        has_error_attr,
        f"hasattr(ev, 'error') = {has_error_attr}"
        + (f", ev.error={getattr(ev, 'error', None)!r}" if has_error_attr else ""),
    )

    criterion_tests_present()
    criterion_original_repro()

    print("\n=== SUMMARY ===")
    all_pass = True
    for name, (ok, detail) in RESULTS.items():
        print(f"{'PASS' if ok else 'FAIL'}: {name} -- {detail}")
        if not ok:
            all_pass = False
    print(f"\nOVERALL: {'ALL CRITERIA PASS' if all_pass else 'SOME CRITERIA FAILED'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
