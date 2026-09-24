"""Verify #135 on 3ed3099: docstring + docs + test cover the
status/has_dormant_invocations ordering caveat for
from_snapshot(restart_services=True).

Acceptance criteria (from gh issue #135):
1. `restart_services` docstring in base_interpreter.py's from_snapshot
   documents the status/has_dormant_invocations ordering caveat.
2. docs/ guide page for persistence/restore mentions the same caveat
   with a code example.
3. A test asserts the documented ordering (has_dormant_invocations /
   has_dormant_timers behavior around start()).
4. The original repro (R4-37) either exits 0, or continues to
   demonstrate the (now-documented, still-present) ordering -- i.e.
   exit 1 is acceptable IFF the docs/docstring caveat is present (this
   is the "FIXED via documentation, not via behavior change" path
   explicitly allowed by the issue).

Exits 0 only if all criteria pass.
"""
import os
import re
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
    "R4-37_restart_services_no_signal.py"
)


def check(label, cond):
    print(f"[{'OK' if cond else 'FAIL'}] {label}")
    return cond


def main() -> int:
    ok = True

    # 1. Docstring caveat in base_interpreter.py
    src = (REPO / "src/xstate_statemachine/base_interpreter.py").read_text(
        encoding="utf-8"
    )
    m = re.search(
        r"restart_services \(bool\):.*?(?=\n\s*\w+ \(|\"\"\")", src, re.S
    )
    docstring_block = m.group(0) if m else ""
    has_status_caveat = (
        "status" in docstring_block
        and "has_dormant_invocations" in docstring_block
        and "#135" in docstring_block
    )
    ok &= check(
        "1. from_snapshot docstring documents status/has_dormant_invocations ordering (#135)",
        has_status_caveat,
    )

    # 2. docs guide page mentions the caveat with a code example
    guide = (REPO / "docs/_guide/snapshots.md").read_text(encoding="utf-8")
    has_guide_caveat = (
        "not a liveness signal" in guide
        and "has_dormant_invocations" in guide
        and "#135" in guide
        and "```python" in guide  # has code examples somewhere in the doc
    )
    ok &= check(
        "2. docs/_guide/snapshots.md documents caveat with code example",
        has_guide_caveat,
    )

    # 3. Test asserts documented ordering (has_dormant_invocations/timers)
    tests = (REPO / "tests/test_round4_findings.py").read_text(encoding="utf-8")
    has_test = (
        "has_dormant_timers" in tests or "has_dormant_invocations" in tests
    )
    ok &= check(
        "3. tests/test_round4_findings.py exercises has_dormant_invocations/timers",
        has_test,
    )

    # 4. Original repro: exit 1 acceptable IFF documented (criteria 1&2 hold)
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    result = subprocess.run(
        [PY, str(REPRO)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO),
    )
    print("--- repro stdout ---")
    print(result.stdout)
    repro_exit = result.returncode
    repro_acceptable = (repro_exit == 0) or (
        repro_exit == 1 and has_status_caveat and has_guide_caveat
    )
    ok &= check(
        f"4. repro exit={repro_exit} acceptable given documentation state",
        repro_acceptable,
    )

    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
