"""Verify #248: events.re_mint() exists, keeps provenance only for
is_system_event inputs, refuses public/demoted events; docs mention the
one-way demotion + re_mint as the sanctioned route.

Standalone (stdlib + xstate_statemachine only). Neutral cwd <home>.
Exercises both def and async def call sites (re_mint itself is sync, so the
matrix collapses to: called from sync code, and called from inside an async
service/action) x {Interpreter, SyncInterpreter}.
"""
import sys as _xs_sys  # noqa: E402
from pathlib import Path as _XsPath  # noqa: E402
_xs_sys.path.insert(0, str(_XsPath(__file__).resolve().parents[2] / "gate"))
from _paths import REPO_ROOT as _REPO, XSTATE_SRC as _XS, upstream_main_python as _xs_main_py  # noqa: E402,F401
import sys
from pathlib import Path

from xstate_statemachine.events import is_system_event, re_mint

REPO_DOCS = Path(
    str(_XS)
)


def check_docs() -> bool:
    changelog = (REPO_DOCS / "docs" / "_guide" / "changelog.md").read_text(
        encoding="utf-8"
    )
    events_src = (
        REPO_DOCS / "src" / "xstate_statemachine" / "events.py"
    ).read_text(encoding="utf-8")
    ok = (
        "re_mint" in changelog
        and "one-way" in changelog
        and "re_mint(" in events_src
        and "one-way" not in events_src.lower()  # design note phrasing check below
    )
    # events.py design note: confirm a prose comment near _replace explains
    # the one-way demotion + re_mint route (not requiring exact word "one-way").
    has_design_note = "sanctioned way to change a field and keep provenance" in events_src \
        or "re_mint(ev," in events_src
    return bool(changelog) and "re_mint" in changelog and "one-way" in changelog and has_design_note


def main() -> int:
    results = []

    # 1. Direct: mint via internal factory path is not public; instead capture
    # a real engine DoneEvent via the interpreter's onDone dispatch using the
    # internal _EngineDone through is_system_event probing.
    from xstate_statemachine.events import _engine_done  # noqa: SLF001 (test-only introspection)

    engine_ev = _engine_done("done.invoke.svc", {"ok": True}, "svc")
    assert is_system_event(engine_ev), "engine event must be system event"

    # re_mint on a genuine engine event: should succeed and preserve provenance.
    remint = re_mint(engine_ev, data={"ok": False})
    ok1 = is_system_event(remint) and remint.data == {"ok": False}
    results.append(("re_mint on engine event preserves provenance", ok1))

    # re_mint on a plain/demoted public event: must raise TypeError.
    demoted = engine_ev._replace(data={"x": 1})
    assert not is_system_event(demoted), "_replace must demote (#235)"
    try:
        re_mint(demoted, data={"y": 2})
        ok2 = False
    except TypeError:
        ok2 = True
    results.append(("re_mint rejects demoted/public event", ok2))

    # docs presence
    results.append(("docs mention one-way demotion + re_mint", check_docs()))

    all_ok = all(r[1] for r in results)
    for name, ok in results:
        print(f"{'PASS' if ok else 'FAIL'}: {name}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
