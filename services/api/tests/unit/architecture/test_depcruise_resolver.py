"""Unit tests for `resolve_depcruise`: it must only ever resolve a local,
lockfile-pinned binary and never a bare `npx` command (C-13.5: no network /
registry fetch from tests). Uses `tmp_path` fake repo roots; no subprocess.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

from tests.unit.architecture import test_negative_arch_violations as neg


def _bin_name() -> str:
    return "depcruise.cmd" if sys.platform == "win32" else "depcruise"


def test_resolve_depcruise_local_bin_returns_explicit_path(tmp_path: Path) -> None:
    bin_dir = tmp_path / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / _bin_name()).write_text("", encoding="utf-8")
    cmd = neg.resolve_depcruise(tmp_path)
    assert cmd == [str(bin_dir / _bin_name())]
    assert Path(cmd[0]).parent.name == ".bin"


def test_resolve_depcruise_pnpm_exec_requires_local_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(neg.shutil, "which", lambda name: "/usr/bin/pnpm")
    assert neg.resolve_depcruise(tmp_path) is None
    (tmp_path / "node_modules" / "dependency-cruiser").mkdir(parents=True)
    assert neg.resolve_depcruise(tmp_path) == ["/usr/bin/pnpm", "exec", "depcruise"]


def test_resolve_depcruise_nothing_installed_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(neg.shutil, "which", lambda name: None)
    assert neg.resolve_depcruise(tmp_path) is None


def test_resolve_depcruise_never_returns_bare_npx(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(neg.shutil, "which", lambda name: f"/usr/bin/{name}")
    (tmp_path / "node_modules" / "dependency-cruiser").mkdir(parents=True)
    cmd = neg.resolve_depcruise(tmp_path)
    assert cmd is not None
    assert Path(cmd[0]).name not in {"npx", "npx.cmd"}


def test_negative_arch_module_has_no_npx_literal() -> None:
    """No code path in the arch tests may build a command containing "npx"."""
    tree = ast.parse(Path(neg.__file__).read_text(encoding="utf-8"))
    literals = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant)}
    assert "npx" not in literals
