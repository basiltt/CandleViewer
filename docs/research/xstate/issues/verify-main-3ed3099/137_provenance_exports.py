"""Verify #137 on 3ed3099: is_system_event / system_event (and related
provenance symbols) exported from package root + documented.

Acceptance criteria (from gh issue #137):
1. is_system_event and system_event are present in
   xstate_statemachine.__all__ and importable from the package root.
2. A new guide page documents provenance semantics and their
   relationship to strict/onUnhandled/"*".
3. tests/test_public_api.py (or equivalent) asserts both names are in
   __all__ and importable.
4. repro/R4-39_provenance_unexported.py exits 0.

Exits 0 only if all criteria pass.
"""
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(
    "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine"
)
PY = str(REPO / ".venv-main" / "Scripts" / "python")
REPRO = Path(
    "C:/Users/basil/Desktop/Projects/FullStackProjects/CandleViewer/docs/"
    "research/xstate/issues/post-5e07ba8/new/repro/"
    "R4-39_provenance_unexported.py"
)

sys.path.insert(0, str(REPO / "src"))


def check(label, cond):
    print(f"[{'OK' if cond else 'FAIL'}] {label}")
    return cond


def main() -> int:
    ok = True

    import xstate_statemachine as xsm

    all_list = getattr(xsm, "__all__", [])
    exported = (
        "is_system_event" in all_list
        and "system_event" in all_list
        and hasattr(xsm, "is_system_event")
        and hasattr(xsm, "system_event")
    )
    ok &= check("1. is_system_event/system_event in __all__ and importable from root", exported)

    # 2. guide page docs
    guide_dir = REPO / "docs" / "_guide"
    candidates = list(guide_dir.glob("*provenance*")) + list(guide_dir.glob("*event*"))
    guide_hit = None
    for f in guide_dir.glob("*.md"):
        text = f.read_text(encoding="utf-8", errors="ignore")
        if "is_system_event" in text and "system_event" in text and (
            "strict" in text or "onUnhandled" in text or "wildcard" in text
        ):
            guide_hit = f
            break
    ok &= check(
        f"2. A docs/_guide page documents provenance + strict/onUnhandled/wildcard relation"
        + (f" (found in {guide_hit.name})" if guide_hit else ""),
        guide_hit is not None,
    )

    # 3. test asserting export
    tests = (REPO / "tests/test_round4_findings.py").read_text(encoding="utf-8")
    has_test = "test_exported_from_root" in tests and "is_system_event" in tests
    ok &= check("3. Test asserts export/importability (test_exported_from_root)", has_test)

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    result = subprocess.run([PY, str(REPRO)], capture_output=True, text=True, env=env, cwd=str(REPO))
    print("--- repro stdout ---")
    print(result.stdout)
    ok &= check(f"4. repro exit=={result.returncode} == 0", result.returncode == 0)

    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
