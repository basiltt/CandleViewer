#!/usr/bin/env python3
"""E03-T07 scope delta (STRIDE R2, dependency confusion,
`docs/plan/threat-models/E03-supply-chain.md` §4.4/§7.1): every internal
`@candleviewer/*` package name resolved during install MUST come from the
workspace, never from a public registry. Installing an internal-scoped name
from `registry.npmjs.org` (a dependency-confusion attack: someone publishes
a public `@candleviewer/<name>` package) must fail closed, not silently
substitute a public package.

Two checks, both required:
  1. Every `@candleviewer/*` *dependency reference* anywhere in the
     workspace (`dependencies`/`devDependencies`/`peerDependencies` of every
     `package.json`) resolves to a workspace package declared in
     `pnpm-workspace.yaml` (`packages/*`, `apps/*`) — i.e. the name is one we
     actually publish internally, not a typo/placeholder that would fall
     through to the public registry.
  2. `pnpm-lock.yaml` records that resolution as `link:`/workspace, never a
     registry tarball URL, for every `@candleviewer/*` package.

Exit codes: 0 clean, 1 violation found, 2 internal error (bad path / repo
files missing).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

SCOPE = "@candleviewer/"


def _iter_package_jsons(root: Path) -> list[Path]:
    found = [root / "package.json"]
    for pattern in ("apps/*/package.json", "packages/*/package.json"):
        found.extend(sorted(root.glob(pattern)))
    return [p for p in found if p.exists()]


def _workspace_package_names(root: Path) -> set[str]:
    names: set[str] = set()
    for pkg_json in _iter_package_jsons(root):
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"error: invalid JSON in {pkg_json}: {exc}") from exc
        name = data.get("name")
        if isinstance(name, str) and name.startswith(SCOPE):
            names.add(name)
    return names


def _referenced_candleviewer_deps(root: Path) -> dict[str, list[Path]]:
    """name -> list of package.json files referencing it as a dependency."""
    refs: dict[str, list[Path]] = {}
    dep_keys = ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies")
    for pkg_json in _iter_package_jsons(root):
        data = json.loads(pkg_json.read_text(encoding="utf-8"))
        for key in dep_keys:
            for name in data.get(key, {}) or {}:
                if name.startswith(SCOPE):
                    refs.setdefault(name, []).append(pkg_json)
    return refs


def check_dependency_references(root: Path) -> list[str]:
    """Every referenced @candleviewer/* name must be a real workspace package."""
    workspace_names = _workspace_package_names(root)
    refs = _referenced_candleviewer_deps(root)
    violations = []
    for name, referencing_files in refs.items():
        if name not in workspace_names:
            files = ", ".join(str(f.relative_to(root)) for f in referencing_files)
            violations.append(
                f"'{name}' is referenced as a dependency in [{files}] but is not a "
                "workspace package name — this would resolve from the public registry "
                "(dependency confusion; STRIDE R2, E03-supply-chain.md §4.4)"
            )
    return violations


# pnpm v9+ lockfile resolution entries for a workspace package look like
# `resolution: {integrity: ...}` is ABSENT and instead the importer's
# dependency entry carries `version: link:../../packages/foo`. A registry
# resolution instead has a `resolution: {integrity: sha512-...}` block. We
# scan for any `@candleviewer/<name>` package block in `packages:` that is
# NOT paired with a `link:` version reference from an importer, which would
# indicate a registry-resolved copy sneaking in.
_LOCKFILE_PKG_HEADER_RE = re.compile(r"^\s*'?(@candleviewer/[^'@\s:]+)@")


def check_lockfile_resolution(root: Path) -> list[str]:
    lockfile = root / "pnpm-lock.yaml"
    if not lockfile.exists():
        return [f"pnpm-lock.yaml not found at {lockfile}"]
    try:
        docs = list(yaml.safe_load_all(lockfile.read_text(encoding="utf-8")))
    except yaml.YAMLError as exc:
        raise SystemExit(f"error: invalid YAML in {lockfile}: {exc}") from exc

    violations: list[str] = []
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        packages = doc.get("packages", {}) or {}
        for key, meta in packages.items():
            if not isinstance(key, str) or SCOPE not in key:
                continue
            if not isinstance(meta, dict):
                continue
            resolution = meta.get("resolution", {})
            # A workspace-linked package has no registry `integrity`/`tarball`
            # in its resolution, or is only ever referenced via `link:` from
            # importers. A registry-hosted `@candleviewer/*` entry (integrity
            # hash present, resolved from a URL) is the confusion signature.
            if isinstance(resolution, dict) and (
                "integrity" in resolution or "tarball" in resolution
            ):
                violations.append(
                    f"pnpm-lock.yaml records '{key}' as resolved from a registry "
                    "(integrity/tarball present) instead of the workspace — this is "
                    "exactly the dependency-confusion shape STRIDE R2 warns about"
                )
        importers = doc.get("importers", {}) or {}
        for importer_path, importer_meta in importers.items():
            if not isinstance(importer_meta, dict):
                continue
            for section in ("dependencies", "devDependencies"):
                for name, dep in (importer_meta.get(section, {}) or {}).items():
                    if not name.startswith(SCOPE):
                        continue
                    version = dep.get("version", "") if isinstance(dep, dict) else str(dep)
                    if not str(version).startswith("link:"):
                        violations.append(
                            f"importer '{importer_path}' resolves '{name}' to "
                            f"'{version}', not a workspace link:// reference"
                        )
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args(argv)

    root = args.root.resolve()
    if not (root / "pnpm-workspace.yaml").exists():
        print(
            f"error: {root} does not look like the repo root (no pnpm-workspace.yaml)",
            file=sys.stderr,
        )
        return 2

    violations = check_dependency_references(root) + check_lockfile_resolution(root)
    if violations:
        print("CI-SEC-001: internal package registry-scope guard failed:", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        return 1

    print("check_internal_package_scope: OK — all @candleviewer/* deps resolve to the workspace")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
