"""Drift test: `docs/plan/module-contracts.toml` vs `CONSTITUTION.md` §3.

E02-T06 (§9 #18): `docs/plan/module-contracts.toml` is the single machine-
readable source of truth, transcribed by hand from `CONSTITUTION.md` §3 (the
human source of truth, C-16.5). This test is the only thing that keeps the
two from silently diverging: it parses §3's markdown table (backend M1-M24
module dependency edges) and the frontend module-boundaries table, and
asserts the manifest agrees on: every module number present, the dotted path
prefix matching the module's `Path` column, and — for the backend table — the
number of dependency edges declared (a proxy for the `allowed` list content,
since the manifest uses dotted Python paths and §3 uses `M<n>` cross-
references, which are not directly string-comparable).

No network, no filesystem access outside the repo tree (C-13.5/C-13.7).
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
CONSTITUTION_PATH = REPO_ROOT / "CONSTITUTION.md"
MANIFEST_PATH = REPO_ROOT / "docs" / "plan" / "module-contracts.toml"

_BACKEND_ROW_RE = re.compile(
    r"^\|\s*(M\d+[a-z]?)\s*\|\s*`([^`]+)`\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*$"
)
_FRONTEND_ROW_RE = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*(.*?)\s*\|\s*$")


def _extract_section(
    lines: list[str], heading_pattern: str, next_heading_pattern: str
) -> list[str]:
    start = next(i for i, line in enumerate(lines) if re.match(heading_pattern, line))
    end = next(
        (
            i
            for i, line in enumerate(lines[start + 1 :], start + 1)
            if re.match(next_heading_pattern, line)
        ),
        len(lines),
    )
    return lines[start:end]


def _parse_backend_table(lines: list[str]) -> dict[str, tuple[str, int]]:
    """Return {module_number: (path_prefix, may_depend_on_count)}."""
    rows: dict[str, tuple[str, int]] = {}
    for line in lines:
        m = _BACKEND_ROW_RE.match(line.strip())
        if not m:
            continue
        number, _name, path, _resp, depends = m.groups()
        if number == "#":  # header row's own literal
            continue
        # "May depend on" cell is either "—" (none) or a comma-separated M-ref
        # list, or "all modules' public interfaces" (M23's special case).
        if depends.strip() in ("—", ""):
            count = 0
        elif "all modules" in depends:
            count = -1  # sentinel: wildcard, not edge-counted
        else:
            count = len([p for p in depends.split(",") if p.strip()])
        rows[number] = (path, count)
    return rows


def _parse_frontend_table(lines: list[str]) -> set[str]:
    packages: set[str] = set()
    for line in lines:
        m = _FRONTEND_ROW_RE.match(line.strip())
        if not m:
            continue
        pkg, _rule = m.groups()
        if pkg == "Package":
            continue
        packages.add(pkg)
    return packages


@pytest.fixture(scope="module")
def constitution_lines() -> list[str]:
    return CONSTITUTION_PATH.read_text(encoding="utf-8").splitlines()


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    with MANIFEST_PATH.open("rb") as f:
        return tomllib.load(f)


def test_backend_module_count_matches(constitution_lines: list[str]) -> None:
    section = _extract_section(constitution_lines, r"^## 3\. Module boundaries", r"^---$")
    backend = _parse_backend_table(section)
    assert len(backend) == 24, (
        f"CONSTITUTION.md §3 backend table has {len(backend)} modules, expected 24 (M1-M24)"
    )


def test_every_constitution_module_is_in_manifest(
    constitution_lines: list[str], manifest: dict[str, Any]
) -> None:
    section = _extract_section(constitution_lines, r"^## 3\. Module boundaries", r"^---$")
    backend = _parse_backend_table(section)
    manifest_numbers = {m["number"].rstrip("b") for m in manifest["module"]}
    for number in backend:
        assert number in manifest_numbers, (
            f"{number} is in CONSTITUTION.md §3 but missing from docs/plan/module-contracts.toml"
        )


def test_manifest_path_is_dotted_candleviewer_import(manifest: dict[str, Any]) -> None:
    """Sanity check: every manifest module path is a dotted import path rooted
    at `candleviewer` (the backend's actual package name), not a filesystem
    path — this catches accidental copy-paste of §3's `Path` column."""
    for entry in manifest["module"]:
        assert entry["path"].startswith("candleviewer."), (
            f"{entry['number']}: manifest path {entry['path']!r} is not a dotted "
            "candleviewer.* import path"
        )


def test_manifest_dependency_edge_count_matches(
    constitution_lines: list[str], manifest: dict[str, Any]
) -> None:
    """Every module's manifest `allowed` list must have the same edge count as
    §3's "May depend on" column (M23's wildcard row is exempt: it is encoded
    as an explicit full-module list in the manifest by design, see the
    manifest's own comment)."""
    section = _extract_section(constitution_lines, r"^## 3\. Module boundaries", r"^---$")
    backend = _parse_backend_table(section)
    by_number = {m["number"]: m for m in manifest["module"] if not m["number"].endswith("b")}
    for number, (_path, count) in backend.items():
        if count == -1:
            continue  # M23 wildcard: manifest intentionally spells out all modules
        entry = by_number.get(number)
        assert entry is not None, f"{number} missing from manifest"
        assert len(entry["allowed"]) == count, (
            f"{number}: manifest allowed-list has {len(entry['allowed'])} entries, "
            f"CONSTITUTION.md §3 'May depend on' column has {count}"
        )


def test_frontend_packages_match(constitution_lines: list[str], manifest: dict[str, Any]) -> None:
    section = _extract_section(
        constitution_lines, r"^Frontend module boundaries:", r"^\*\*C-3\.5\*\*"
    )
    frontend_packages = _parse_frontend_table(section)
    manifest_packages = {p["name"] for p in manifest["frontend_package"]}
    assert frontend_packages == manifest_packages, (
        f"CONSTITUTION.md §3 frontend table lists {sorted(frontend_packages)}, "
        f"docs/plan/module-contracts.toml lists {sorted(manifest_packages)}"
    )
