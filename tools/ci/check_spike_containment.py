#!/usr/bin/env python3
"""E06-X02: spike throwaway-code containment gate.

`docs/plan/02-definition-of-ready-done.md` §5.2 requires spike code be either
promoted with normal DoD, or explicitly marked throwaway and left unmerged.
E06 splits this deliberately: the M0 benchmark harness (E06-K01) and the
seeded fixture generator are *promoted* (merged to `main`, tested, covered);
the three prototype scenes (E06-K02/K03/K04) are *throwaway* and must never
reach `main`.

This check is deliberately crude (ticket "Technical notes": "a path-existence
assertion... does not fail silently"):

1. **Path-existence** — on `main` (and on any branch, since a PR merges into
   `main`), no file may live under a spike-only path (`SPIKE_PATH_MARKERS`).
   If one exists, the check fails with a message explaining the
   promoted-vs-throwaway split and naming the offending path(s).
2. **Import-boundary** — nothing under the *merged* harness paths
   (`HARNESS_PATH_ROOTS`) may import from a spike-only path. This is the
   "harness does not depend on the prototype" acceptance scenario, enforced
   here (a static grep over `import`/`require` specifiers) in addition to the
   ESLint `no-restricted-imports` rule in `packages/chart-engine/eslint.config.mjs`
   — belt and suspenders, since the ESLint rule only runs where `pnpm lint`
   runs, while this script is also invoked as a fast, dependency-free CI gate
   and locally.

Exit codes: 0 clean, 1 violation found, 2 internal error (bad path).

Stdlib only — this must run before any package manager is bootstrapped.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Directories that may exist ONLY on a spike branch (e.g. spike/e06-engine-m0),
# never on `main`. A leading `packages/chart-engine/` scope keeps this from
# accidentally matching an unrelated future `spike/` directory elsewhere in
# the repo (e.g. `docs/plan/spikes/` is a *written-findings* directory, not
# code, and is explicitly promoted — see E06-K02.md).
#
# Deviation (noted in this ticket's PR under "Deviations"): the ticket's own
# example path is `packages/chart-engine/spike/`, which this check enforces
# going forward for E06-K03/E06-K04 and any future spike. E06-K02's prototype
# scene (PR #1509, merged before this ticket) already landed under
# `packages/chart-engine/bench/scenes/` instead of a `spike/` directory — that
# is a pre-existing DoD gap this ticket cannot retroactively fix without
# reopening a closed ticket's scope (out of scope per this ticket's own "Out
# of scope" list, which reserves E06-T03/E06-X01 decisions). Adding that path
# to the forbidden-marker list here would break `main` immediately, which is
# the opposite of what a containment gate is for. `bench/scenes/README.md`
# already documents its throwaway status; a follow-up ticket should either
# promote it properly or relocate it under `spike/` before Epic close per the
# archival procedure in this ticket's Definition of Done.
SPIKE_PATH_MARKERS: tuple[str, ...] = ("packages/chart-engine/spike/",)

# Paths that are the *promoted* harness — these must never import from a
# spike-only path.
HARNESS_PATH_ROOTS: tuple[str, ...] = (
    "packages/chart-engine/src/",
    "packages/chart-engine/bench/",
)

# import/require specifiers pointing at a relative path — enough to catch
# `./scenes/scene-a.mjs`, `../scenes/scene-a`, etc. without a full JS parser.
_IMPORT_SPEC_RE = re.compile(
    r"""(?:from\s+|require\(\s*|import\(\s*)['"](?P<spec>\.[^'"]+)['"]"""
)


def find_spike_paths(root: Path) -> list[str]:
    """Return repo-relative paths that exist under a spike-only marker."""
    hits: list[str] = []
    for marker in SPIKE_PATH_MARKERS:
        marker_path = root / marker
        if marker_path.exists():
            hits.append(marker)
    return hits


def _iter_harness_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for rel in HARNESS_PATH_ROOTS:
        base = root / rel
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.suffix in {".ts", ".mjs", ".js", ".ts.mjs"}:
                files.append(path)
    return files


def find_harness_imports_of_spike(root: Path) -> list[str]:
    """Return "file -> spec" strings where a harness file imports a spike path."""
    violations: list[str] = []
    spike_dir_names = {Path(m).name for m in SPIKE_PATH_MARKERS if m.endswith("/")}
    # Also match the marker's parent-relative segment ("scenes", "spike") so a
    # relative import like `../scenes/scene-a.mjs` from a harness file is caught
    # even though the harness file itself does not live under the marker.
    for path in _iter_harness_files(root):
        # A file that itself lives under a spike marker is not "the harness"
        # importing the spike — it *is* spike code (already flagged above).
        rel_posix = path.relative_to(root).as_posix()
        if any(rel_posix.startswith(m) for m in SPIKE_PATH_MARKERS):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for match in _IMPORT_SPEC_RE.finditer(text):
            spec = match.group("spec")
            spec_parts = Path(spec).parts
            if any(part in spike_dir_names for part in spec_parts):
                violations.append(f"{rel_posix} -> {spec}")
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        default=".",
        help="Repo root to check (default: current directory).",
    )
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if not root.exists():
        print(f"error: --root {root} does not exist", file=sys.stderr)
        return 2

    spike_paths = find_spike_paths(root)
    if spike_paths:
        print(
            "CI-SPIKE-001: throwaway prototype code found on this branch under a "
            "spike-only path. Per docs/plan/02-definition-of-ready-done.md §5.2, "
            "spike code is either promoted (normal DoD) or left unmerged on its "
            "own spike branch — it may not reach `main` unmodified. E06 promoted "
            "the M0 benchmark harness (E06-K01) but left the prototype scenes "
            "(E06-K02/K03/K04) throwaway; see docs/plan/spikes/E06-K02.md and "
            "packages/chart-engine/bench/scenes/README.md for the split this "
            "check enforces.\n\nOffending path(s):\n"
            + "\n".join(f"  - {p}" for p in spike_paths),
            file=sys.stderr,
        )
        return 1

    import_violations = find_harness_imports_of_spike(root)
    if import_violations:
        print(
            "CI-SPIKE-002: the promoted benchmark harness imports from a "
            "spike-only path. The harness must never depend on throwaway "
            'prototype code (E06-X02 acceptance criterion "The harness does '
            'not depend on the prototype").\n\nOffending import(s):\n'
            + "\n".join(f"  - {v}" for v in import_violations),
            file=sys.stderr,
        )
        return 1

    print(
        "check_spike_containment: OK — no spike-only paths on this branch, no boundary violations"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
