"""Unit tests for tools/ci/check_internal_package_scope.py (E03-T07 scope
delta, STRIDE R2 dependency confusion).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.check_internal_package_scope import (
    check_dependency_references,
    check_lockfile_resolution,
    main,
)


def _make_workspace(root: Path) -> None:
    (root / "pnpm-workspace.yaml").write_text(
        "packages:\n  - 'apps/*'\n  - 'packages/*'\n", encoding="utf-8"
    )
    (root / "package.json").write_text(json.dumps({"name": "candleviewer"}), encoding="utf-8")
    (root / "apps").mkdir()
    (root / "packages").mkdir()


def _pkg(root: Path, rel: str, name: str, deps: dict[str, str] | None = None) -> None:
    d = root / rel
    d.mkdir(parents=True, exist_ok=True)
    body = {"name": name}
    if deps:
        body["dependencies"] = deps
    (d / "package.json").write_text(json.dumps(body), encoding="utf-8")


def test_real_workspace_package_reference_passes(tmp_path: Path) -> None:
    _make_workspace(tmp_path)
    _pkg(tmp_path, "packages/ui", "@candleviewer/ui")
    _pkg(tmp_path, "apps/web", "@candleviewer/web", deps={"@candleviewer/ui": "workspace:*"})
    assert check_dependency_references(tmp_path) == []


def test_typo_or_confused_scoped_dependency_fails(tmp_path: Path) -> None:
    _make_workspace(tmp_path)
    _pkg(tmp_path, "packages/ui", "@candleviewer/ui")
    _pkg(
        tmp_path,
        "apps/web",
        "@candleviewer/web",
        deps={"@candleviewer/uii": "workspace:*"},  # typo — not a real workspace package
    )
    violations = check_dependency_references(tmp_path)
    assert len(violations) == 1
    assert "@candleviewer/uii" in violations[0]
    assert "dependency confusion" in violations[0]


def test_lockfile_registry_resolved_scoped_package_fails(tmp_path: Path) -> None:
    _make_workspace(tmp_path)
    lockfile = tmp_path / "pnpm-lock.yaml"
    lockfile.write_text(
        "packages:\n"
        "  '@candleviewer/ui@1.0.0':\n"
        "    resolution: {integrity: sha512-fakefakefake}\n",
        encoding="utf-8",
    )
    violations = check_lockfile_resolution(tmp_path)
    assert len(violations) == 1
    assert "@candleviewer/ui@1.0.0" in violations[0]


def test_lockfile_workspace_link_resolution_passes(tmp_path: Path) -> None:
    _make_workspace(tmp_path)
    lockfile = tmp_path / "pnpm-lock.yaml"
    lockfile.write_text(
        "importers:\n"
        "  apps/web:\n"
        "    dependencies:\n"
        "      '@candleviewer/ui':\n"
        "        version: link:../../packages/ui\n",
        encoding="utf-8",
    )
    violations = check_lockfile_resolution(tmp_path)
    assert violations == []


def test_lockfile_importer_registry_version_fails(tmp_path: Path) -> None:
    _make_workspace(tmp_path)
    lockfile = tmp_path / "pnpm-lock.yaml"
    lockfile.write_text(
        "importers:\n"
        "  apps/web:\n"
        "    dependencies:\n"
        "      '@candleviewer/ui':\n"
        "        version: 1.0.0\n",
        encoding="utf-8",
    )
    violations = check_lockfile_resolution(tmp_path)
    assert len(violations) == 1
    assert "not a workspace link" in violations[0]


def test_main_exits_1_on_violation(tmp_path: Path) -> None:
    _make_workspace(tmp_path)
    _pkg(tmp_path, "packages/ui", "@candleviewer/ui")
    _pkg(tmp_path, "apps/web", "@candleviewer/web", deps={"@candleviewer/bogus": "1.0.0"})
    (tmp_path / "pnpm-lock.yaml").write_text("importers: {}\n", encoding="utf-8")
    rc = main(["--root", str(tmp_path)])
    assert rc == 1


def test_main_exits_0_on_clean_workspace(tmp_path: Path) -> None:
    _make_workspace(tmp_path)
    _pkg(tmp_path, "packages/ui", "@candleviewer/ui")
    (tmp_path / "pnpm-lock.yaml").write_text("importers: {}\n", encoding="utf-8")
    rc = main(["--root", str(tmp_path)])
    assert rc == 0


def test_main_exits_2_when_not_repo_root(tmp_path: Path) -> None:
    rc = main(["--root", str(tmp_path)])
    assert rc == 2
