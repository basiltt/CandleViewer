"""Tests for `tools/rbac/generate.py` (E09-T03).

Runs the generator as a subprocess (same convention as
`services/api/tests/contract/test_generate_protocol_models.py`) so the test
exercises the exact code path CI's `generated-code` check runs.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "tools" / "rbac" / "generate.py"
ENUM_PATH = REPO_ROOT / "services" / "api" / "candleviewer" / "auth" / "generated_permissions.py"
SEED_PATH = REPO_ROOT / "services" / "api" / "candleviewer" / "auth" / "rbac_seed.json"


def _run(*extra_args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 — fixed argv, no shell, trusted script under test
        [sys.executable, str(SCRIPT), *extra_args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_check_passes_against_committed_output() -> None:
    """The committed `generated_permissions.py`/`rbac_seed.json` are exactly
    what the generator produces today — CI's `generated-code` job runs this
    exact invocation."""
    result = _run("--check")
    assert result.returncode == 0, result.stderr


def test_regenerating_twice_is_byte_identical() -> None:
    before_enum = ENUM_PATH.read_text(encoding="utf-8")
    before_seed = SEED_PATH.read_text(encoding="utf-8")
    try:
        first = _run()
        assert first.returncode == 0, first.stderr
        after_first_enum = ENUM_PATH.read_text(encoding="utf-8")
        after_first_seed = SEED_PATH.read_text(encoding="utf-8")

        second = _run()
        assert second.returncode == 0, second.stderr
        after_second_enum = ENUM_PATH.read_text(encoding="utf-8")
        after_second_seed = SEED_PATH.read_text(encoding="utf-8")

        assert after_first_enum == after_second_enum
        assert after_first_seed == after_second_seed
    finally:
        ENUM_PATH.write_text(before_enum, encoding="utf-8")
        SEED_PATH.write_text(before_seed, encoding="utf-8")


def test_generated_enum_imports_cleanly() -> None:
    import importlib

    import candleviewer.auth.generated_permissions as mod

    importlib.reload(mod)
    assert len(list(mod.Permission)) == 36
    assert {s.value for s in mod.Scope} == {"none", "self", "granted_accounts"}
