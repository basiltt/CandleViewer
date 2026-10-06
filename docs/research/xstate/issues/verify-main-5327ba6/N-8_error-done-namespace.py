"""Verification of GH#79 (LC label: N-8) on main @ 5327ba6.

Issue: the reserved-namespace prefix exemption
(`done.`, `error.`, `after.`, `xstate.`, `___xstate`) silently made
user-sent events named e.g. `done.review` / `error.myapp.validation`
invisible to `"*"` and exempt from `onUnhandled: "error"`, because the
exemption is a prefix test on the event NAME, not on provenance.

Per the task's "need": the underlying runtime behaviour (invisible to
`"*"`, exempt from `onUnhandled`) is UNCHANGED and now merely documented --
what actually shipped is:
  - `events.SYSTEM_EVENT_PREFIXES` is importable (single source of truth).
  - `create_machine()` emits a `UserWarning` for an `on` key in a reserved
    namespace that the engine will never synthesise (e.g. `done.review`,
    `error.validation`).
  - `create_machine()` does NOT warn for engine-shaped keys
    (`done.invoke.<id>`, `error.platform.<id>`, `after.<ms>`, `xstate.*`),
    since those really are engine traffic.

This script checks ALL of GH#79's literal acceptance criteria (so the
mismatch between the issue's ask and what shipped is explicit), plus the
"need" behaviours, and classifies accordingly. Exit code reflects whether
the issue's own written acceptance criteria pass -- expect this to be
non-zero, since the chosen fix is documented behaviour, not the runtime
change the acceptance criteria describe. See the .result.md for the
PARTIAL classification and reasoning.
"""

from __future__ import annotations
import sys as _xs_sys  # noqa: E402
from pathlib import Path as _XsPath  # noqa: E402
_xs_sys.path.insert(0, str(_XsPath(__file__).resolve().parents[2] / "gate"))
from _paths import REPO_ROOT as _REPO, XSTATE_SRC as _XS, upstream_main_python as _xs_main_py  # noqa: E402,F401

import asyncio
import subprocess
import sys
import warnings
from pathlib import Path

from xstate_statemachine import Interpreter, MachineLogic, create_machine

RESULTS: dict[str, tuple[bool, str]] = {}


def record(name: str, ok: bool, detail: str) -> None:
    RESULTS[name] = (ok, detail)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")


def criterion_importable() -> None:
    try:
        from xstate_statemachine.events import SYSTEM_EVENT_PREFIXES

        ok = isinstance(SYSTEM_EVENT_PREFIXES, tuple) and all(
            isinstance(p, str) for p in SYSTEM_EVENT_PREFIXES
        )
        record(
            "need_SYSTEM_EVENT_PREFIXES_importable",
            ok,
            f"events.SYSTEM_EVENT_PREFIXES = {SYSTEM_EVENT_PREFIXES!r}",
        )
    except ImportError as exc:
        record("need_SYSTEM_EVENT_PREFIXES_importable", False, f"ImportError: {exc}")


def criterion_warns_for_reserved_on_key() -> None:
    """create_machine() warns UserWarning for a user 'on' key the engine
    will never synthesise (done.review, error.validation)."""
    cfg = {
        "id": "wc",
        "initial": "a",
        "states": {
            "a": {
                "on": {
                    "done.review": {"target": "a"},
                    "error.validation": {"target": "a"},
                }
            }
        },
    }
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        create_machine(cfg)
        user_warnings = [x for x in w if issubclass(x.category, UserWarning)]
    ok = len(user_warnings) >= 1 and any(
        "reserved namespace" in str(x.message) for x in user_warnings
    )
    record(
        "need_warns_for_done_review_error_validation",
        ok,
        f"{len(user_warnings)} UserWarning(s): "
        + "; ".join(str(x.message)[:120] for x in user_warnings),
    )


def criterion_no_warn_for_engine_shaped_keys() -> None:
    """create_machine() must NOT warn for done.invoke.<id>, error.platform.<id>,
    after.<ms> -- those really are engine-synthesised shapes."""
    cfg = {
        "id": "eng",
        "initial": "a",
        "states": {
            "a": {
                "invoke": {"src": "svc", "id": "svc1"},
                "after": {100: "b"},
                "on": {
                    "done.invoke.svc1": {"target": "b"},
                    "error.platform.svc1": {"target": "b"},
                    "after.100": {"target": "b"},
                },
            },
            "b": {},
        },
    }

    async def svc(interp, ctx, event):
        return None

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        create_machine(cfg, logic=MachineLogic(services={"svc": svc}))
        user_warnings = [x for x in w if issubclass(x.category, UserWarning)]
    reserved_warnings = [
        x for x in user_warnings if "reserved namespace" in str(x.message)
    ]
    ok = len(reserved_warnings) == 0
    record(
        "need_no_warn_for_engine_shaped_keys",
        ok,
        f"reserved-namespace warnings for engine-shaped keys: {len(reserved_warnings)}"
        + (f" -- {[str(x.message)[:150] for x in reserved_warnings]}" if reserved_warnings else ""),
    )


async def _wildcard_case() -> list[str]:
    cfg = {
        "id": "wc2",
        "initial": "a",
        "context": {"caught": []},
        "states": {"a": {"on": {"*": {"actions": ["note"]}}}},
    }

    def note(_interp, ctx, event, _action):
        ctx["caught"].append(event.type)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        machine = create_machine(cfg, logic=MachineLogic(actions={"note": note}))
    interp = Interpreter(machine)
    await interp.start()
    for ev in ("PLAIN", "error.myapp.validation", "done.review", "my.namespaced"):
        await interp.send(ev)
    await asyncio.sleep(0.05)
    caught = list(interp.context["caught"])
    try:
        await asyncio.wait_for(interp.stop(), timeout=5.0)
    except Exception:  # noqa: BLE001
        pass
    return caught


async def _onunhandled_case() -> dict[str, str]:
    cfg = {
        "id": "ou2",
        "initial": "a",
        "onUnhandled": "error",
        "states": {"a": {"on": {"PING": {"target": "a", "reenter": True}}}},
    }
    out: dict[str, str] = {}
    for ev in ("UNKNOWN_PLAIN", "done.review", "error.validation"):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            machine = create_machine(cfg)
        interp = Interpreter(machine)
        await interp.start()
        try:
            await interp.send(ev)
            await asyncio.sleep(0.05)
            out[ev] = "no error" if interp.is_running else "stopped"
        except Exception as exc:  # noqa: BLE001
            out[ev] = type(exc).__name__
        try:
            await asyncio.wait_for(interp.stop(), timeout=5.0)
        except Exception:  # noqa: BLE001
            pass
    return out


async def literal_criteria_runtime_behaviour() -> None:
    """GH#79's literal, checkable acceptance criteria:
      - a user-sent error.myapp.validation matches on: {"*": ...}
      - a user-sent, unhandled done.review trips onUnhandled: "error"
      - engine-synthesised done.invoke.*/error.platform.*/after.*/xstate.*
        remain exempt (no regression)
    """
    caught = await _wildcard_case()
    record(
        "literal_criterion_wildcard_matches_error_myapp_validation",
        "error.myapp.validation" in caught,
        f"caught={caught}",
    )
    record(
        "literal_criterion_wildcard_matches_done_review",
        "done.review" in caught,
        f"caught={caught}",
    )

    unhandled = await _onunhandled_case()
    record(
        "literal_criterion_onUnhandled_trips_for_done_review",
        unhandled.get("done.review") not in (None, "no error"),
        f"observed={unhandled.get('done.review')}",
    )
    record(
        "literal_criterion_onUnhandled_trips_for_error_validation",
        unhandled.get("error.validation") not in (None, "no error"),
        f"observed={unhandled.get('error.validation')}",
    )
    record(
        "literal_criterion_control_unknown_plain_still_trips",
        unhandled.get("UNKNOWN_PLAIN") not in (None, "no error"),
        f"observed={unhandled.get('UNKNOWN_PLAIN')}",
    )
    record(
        "literal_criterion_control_wildcard_plain_still_matches",
        "PLAIN" in caught and "my.namespaced" in caught,
        f"caught={caught}",
    )


def criterion_docs_mention_reserved_prefixes() -> None:
    """The reserved prefixes should be documented in the events guide,
    onUnhandled section and strict-mode section."""
    docs_root = Path(
        str(_XS / 'docs')
    )
    hits = []
    if docs_root.exists():
        for f in docs_root.rglob("*.md*"):
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:  # noqa: BLE001
                continue
            if "reserved namespace" in text.lower() or "SYSTEM_EVENT_PREFIXES" in text:
                hits.append(str(f.relative_to(docs_root)))
    record(
        "need_docs_mention_reserved_prefixes",
        len(hits) > 0,
        f"{len(hits)} doc file(s) mention it: {hits[:5]}",
    )


def tests_present() -> None:
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
        "test_user_event_in_reserved_namespace_matches_wildcard",
        "test_user_event_in_reserved_namespace_trips_onunhandled_error",
        "test_engine_synthesised_events_remain_exempt",
    ]
    # allow near-matches since the actual test file renamed things slightly
    present = {}
    for name in expected:
        present[name] = [fn for fn, text in found_in if name in text]
    missing = [name for name, locs in present.items() if not locs]
    record(
        "acceptance_tests_named_in_issue_present",
        not missing,
        f"missing={missing}" if missing else f"present: {present}",
    )
    # also record what related-but-differently-named tests DO exist
    related = [
        (fn, name)
        for fn, text in found_in
        for name in ["reserved_namespace", "reserved_event"]
        if name in text.lower().replace(" ", "_")
    ]


def original_repro_exit_code() -> None:
    repro = Path(
        str(_REPO / 'docs/research/xstate/issues/new-0.8.0/repro/N-08_error-done-namespace-invisible.py')
    )
    py = _xs_main_py()
    import os

    proc = subprocess.run(
        [py, str(repro)],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
    )
    print("--- original repro stdout ---")
    print(proc.stdout)
    if proc.stderr:
        print("--- original repro stderr ---")
        print(proc.stderr)
    # NOTE: this is informational, not a pass/fail gate by itself here --
    # it directly restates literal_criterion_* above. Recorded for the
    # "also re-run the original repro" instruction.
    record(
        "original_repro_exit_0",
        proc.returncode == 0,
        f"exit code={proc.returncode} (expected 0 only if runtime behaviour changed)",
    )


def main() -> int:
    criterion_importable()
    criterion_warns_for_reserved_on_key()
    criterion_no_warn_for_engine_shaped_keys()
    asyncio.run(literal_criteria_runtime_behaviour())
    criterion_docs_mention_reserved_prefixes()
    tests_present()
    original_repro_exit_code()

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
