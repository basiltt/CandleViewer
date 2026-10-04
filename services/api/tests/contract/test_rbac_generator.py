"""Tests for `tools/rbac/generate.py` (E09-T03).

Runs the generator as a subprocess (same convention as
`services/api/tests/contract/test_generate_protocol_models.py`) so the test
exercises the exact code path CI's `generated-code` check runs.

These tests never write inside the checkout (C-13.7): the write path is
exercised via `--out-dir <tmp_path>`, and the committed artefacts are only
ever *read*. (A previous version regenerated in place and "restored" with a
platform-default `write_text`, which rewrote the committed LF files as CRLF
on Windows — a dirty tree after every `pytest` run.)
"""

from __future__ import annotations

import json
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


def _read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def test_check_passes_against_committed_output() -> None:
    """The committed `generated_permissions.py`/`rbac_seed.json` are exactly
    what the generator produces today — CI's `generated-code` job runs this
    exact invocation."""
    result = _run("--check")
    assert result.returncode == 0, result.stderr


def test_committed_artefacts_round_trip_byte_identical(tmp_path: Path) -> None:
    """Regenerating into a scratch directory reproduces the committed files
    byte-for-byte (content *and* LF line endings), so running the generator
    for real never produces a diff."""
    result = _run("--out-dir", str(tmp_path))
    assert result.returncode == 0, result.stderr

    for committed in (ENUM_PATH, SEED_PATH):
        generated = tmp_path / committed.name
        assert generated.is_file()
        assert _read_bytes(generated) == _read_bytes(committed), committed.name
        assert b"\r" not in _read_bytes(generated), f"{committed.name} must be LF-only"


def test_regenerating_twice_is_byte_identical(tmp_path: Path) -> None:
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"

    first = _run("--out-dir", str(first_dir))
    assert first.returncode == 0, first.stderr
    second = _run("--out-dir", str(second_dir))
    assert second.returncode == 0, second.stderr

    for name in (ENUM_PATH.name, SEED_PATH.name):
        assert _read_bytes(first_dir / name) == _read_bytes(second_dir / name)


def test_generator_does_not_touch_the_checkout(tmp_path: Path) -> None:
    """Explicit no-side-effect guard (C-13.7): after a `--out-dir` run the
    committed files have the same bytes and mtimes as before."""
    before = {p: (_read_bytes(p), p.stat().st_mtime_ns) for p in (ENUM_PATH, SEED_PATH)}
    result = _run("--out-dir", str(tmp_path))
    assert result.returncode == 0, result.stderr
    after = {p: (_read_bytes(p), p.stat().st_mtime_ns) for p in (ENUM_PATH, SEED_PATH)}
    assert before == after


def test_generated_enum_imports_cleanly() -> None:
    import importlib

    import candleviewer.auth.generated_permissions as mod

    importlib.reload(mod)
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    assert len(list(mod.Permission)) == len(seed["permissions"])
    assert {s.value for s in mod.Scope} == {"none", "self", "granted_accounts"}
