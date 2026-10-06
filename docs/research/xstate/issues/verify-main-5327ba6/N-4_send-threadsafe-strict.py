"""Verification of GH#78 / LC-52... (LC label: N-4) on main @ 5327ba6.

Issue: `send_threadsafe()` bypassed `strict` mode and `event_schemas`
validation -- the one guardrail #37 made mandatory for cross-thread callers
was the one path that skipped it.

Acceptance criteria (from GH#78):
  1. `repro/N-04_send-threadsafe-bypasses-strict.py` exits 0.
  2. `send_threadsafe("FIL")` on a `strict: True` machine raises/reports
     `UnknownEventError` with the difflib suggestion.
  3. `send_threadsafe("FILL", qty=-1)` with a registered schema raises/reports
     `InvalidEventPayloadError` **and does not transition**.
  4. Validation for `event_schemas` applies regardless of the `strict`
     setting on this path too, matching `send()`.
  5. Tests added:
       tests/test_strict_mode.py::test_send_threadsafe_rejects_unknown_event
       tests/test_strict_mode.py::test_send_threadsafe_validates_payload_schema
       tests/test_strict_mode.py::test_send_threadsafe_invalid_payload_does_not_transition

"need": "see #51 first half" -- also re-check that `send_threadsafe()` applies
`event_schemas` validation even when `strict=False` (criterion 4), since #51
(strict mode) is the first half of the guardrail this issue completes.

Exits 0 only if ALL criteria pass.
"""

from __future__ import annotations
import sys as _xs_sys  # noqa: E402
from pathlib import Path as _XsPath  # noqa: E402
_xs_sys.path.insert(0, str(_XsPath(__file__).resolve().parents[2] / "gate"))
from _paths import REPO_ROOT as _REPO, XSTATE_SRC as _XS, upstream_main_python as _xs_main_py  # noqa: E402,F401

import asyncio
import re
import subprocess
import sys
import threading
from pathlib import Path

from xstate_statemachine import Interpreter, create_machine
from xstate_statemachine.exceptions import InvalidEventPayloadError, UnknownEventError

RESULTS: dict[str, tuple[bool, str]] = {}


def record(name: str, ok: bool, detail: str) -> None:
    RESULTS[name] = (ok, detail)
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}: {detail}")


CFG = {
    "id": "st",
    "initial": "a",
    "strict": True,
    "states": {"a": {"on": {"FILL": {"target": "b"}}}, "b": {}},
}


class QtySchema:
    def validate(self, payload):
        qty = (payload or {}).get("qty")
        if not isinstance(qty, int) or qty <= 0:
            raise ValueError(f"qty must be a positive int, got {qty!r}")


async def criterion_2_and_3() -> None:
    machine = create_machine(CFG, event_schemas={"FILL": QtySchema()})
    interp = Interpreter(machine, strict=True)
    await interp.start()

    # control: ordinary send() path still guards typo
    try:
        await interp.send("FIL")
        control_ok = False
    except UnknownEventError:
        control_ok = True
    except Exception:
        control_ok = False
    record("control_send_typo_rejected", control_ok, "send('FIL') raised UnknownEventError")

    # criterion 2: send_threadsafe() typo raises UnknownEventError, with suggestion
    typo_result: dict[str, object] = {}

    def foreign_typo() -> None:
        try:
            fut = interp.send_threadsafe("FIL")
            if hasattr(fut, "result"):
                fut.result(timeout=5)
            typo_result["exc"] = None
        except Exception as exc:  # noqa: BLE001
            typo_result["exc"] = exc

    t = threading.Thread(target=foreign_typo)
    t.start()
    while t.is_alive():
        await asyncio.sleep(0.01)
    t.join()

    exc = typo_result.get("exc")
    is_unknown = isinstance(exc, UnknownEventError)
    has_suggestion = is_unknown and "did you mean" in str(exc).lower()
    record(
        "criterion_2_threadsafe_typo_raises_unknownevent",
        is_unknown,
        f"got {type(exc).__name__ if exc else None}: {exc}",
    )
    record(
        "criterion_2b_suggestion_present",
        has_suggestion,
        f"message={exc!r}",
    )

    # criterion 3: send_threadsafe() bad payload raises InvalidEventPayloadError
    # and does not transition.
    bad_payload_result: dict[str, object] = {}

    def foreign_bad_payload() -> None:
        try:
            fut = interp.send_threadsafe("FILL", qty=-1)
            if hasattr(fut, "result"):
                fut.result(timeout=5)
            bad_payload_result["exc"] = None
        except Exception as exc2:  # noqa: BLE001
            bad_payload_result["exc"] = exc2

    t2 = threading.Thread(target=foreign_bad_payload)
    t2.start()
    while t2.is_alive():
        await asyncio.sleep(0.01)
    t2.join()

    await asyncio.sleep(0.05)
    states = sorted(interp.current_state_ids)

    exc2 = bad_payload_result.get("exc")
    is_invalid_payload = isinstance(exc2, InvalidEventPayloadError)
    no_transition = states == ["st.a"] or all("b" not in s for s in states)
    record(
        "criterion_3_threadsafe_bad_payload_raises",
        is_invalid_payload,
        f"got {type(exc2).__name__ if exc2 else None}: {exc2}",
    )
    record(
        "criterion_3b_no_transition_occurred",
        no_transition,
        f"final states={states}",
    )

    try:
        await asyncio.wait_for(interp.stop(), timeout=5.0)
    except Exception:  # noqa: BLE001
        pass


async def criterion_4_non_strict_schema_still_applies() -> None:
    """event_schemas validation applies regardless of `strict` (#51 first half)."""
    cfg = {
        "id": "ns",
        "initial": "a",
        # strict NOT set -> default False
        "states": {"a": {"on": {"FILL": {"target": "b"}}}, "b": {}},
    }
    machine = create_machine(cfg, event_schemas={"FILL": QtySchema()})
    interp = Interpreter(machine)  # strict defaults False
    await interp.start()

    result: dict[str, object] = {}

    def foreign() -> None:
        try:
            fut = interp.send_threadsafe("FILL", qty=-1)
            if hasattr(fut, "result"):
                fut.result(timeout=5)
            result["exc"] = None
        except Exception as exc:  # noqa: BLE001
            result["exc"] = exc

    t = threading.Thread(target=foreign)
    t.start()
    while t.is_alive():
        await asyncio.sleep(0.01)
    t.join()

    await asyncio.sleep(0.05)
    states = sorted(interp.current_state_ids)
    exc = result.get("exc")
    ok = isinstance(exc, InvalidEventPayloadError) and all("b" not in s for s in states)
    record(
        "criterion_4_schema_enforced_without_strict",
        ok,
        f"strict=False machine: got {type(exc).__name__ if exc else None}, states={states}",
    )

    try:
        await asyncio.wait_for(interp.stop(), timeout=5.0)
    except Exception:  # noqa: BLE001
        pass


def criterion_5_tests_present() -> None:
    # Issue #78 names `tests/test_strict_mode.py`; on main the module was
    # renamed to `tests/test_strict.py` (test names unchanged). Search
    # across the tests dir so a harmless rename doesn't fail the criterion.
    tests_dir = Path(
        str(_XS / 'tests')
    )
    combined = ""
    found_in = []
    for f in tests_dir.glob("*.py"):
        text = f.read_text(encoding="utf-8")
        combined += text
        found_in.append((f.name, text))
    expected = [
        "test_send_threadsafe_rejects_unknown_event",
        "test_send_threadsafe_validates_payload_schema",
        "test_send_threadsafe_invalid_payload_does_not_transition",
    ]
    missing = [name for name in expected if name not in combined]
    locations = {
        name: [fn for fn, text in found_in if name in text] for name in expected
    }
    record(
        "criterion_5_tests_added",
        not missing,
        f"missing={missing}" if missing else f"all three present: {locations}",
    )


def criterion_1_repro_exits_zero() -> None:
    repro = Path(
        str(_REPO / 'docs/research/xstate/issues/new-0.8.0/repro/N-04_send-threadsafe-bypasses-strict.py')
    )
    py = _xs_main_py()
    proc = subprocess.run(
        [py, str(repro)],
        capture_output=True,
        text=True,
        env={
            **__import__("os").environ,
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        },
    )
    print("--- original repro stdout ---")
    print(proc.stdout)
    if proc.stderr:
        print("--- original repro stderr ---")
        print(proc.stderr)
    record(
        "criterion_1_original_repro_exit_0",
        proc.returncode == 0,
        f"exit code={proc.returncode}",
    )


async def main_async() -> None:
    await criterion_2_and_3()
    await criterion_4_non_strict_schema_still_applies()
    criterion_5_tests_present()


def main() -> int:
    criterion_1_repro_exits_zero()
    asyncio.run(main_async())

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
