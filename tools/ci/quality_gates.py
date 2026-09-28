#!/usr/bin/env python3
"""E02-T10: coverage/bundle-size threshold-guard (C-9.4).

`quality-gates.json` (repo root) declares the per-package coverage floors and
the apps/web bundle-size budget that CONSTITUTION.md §9 (#3, #4, #5, #15)
requires. Thresholds are floors, not targets, and C-9.4 says they may never
be lowered in the same PR that fails them.

This script is mechanical enforcement of C-9.4: it diffs the working tree's
`quality-gates.json` against the same file on `main` (or a given ref) and
fails if any coverage/bundle-size value decreased, unless the changed entry
carries an `"amendment"` key naming the CONSTITUTION.md amendment that
authorised the decrease.

Exit codes: 0 clean (no decrease, or amended decreases only), 1 an
un-amended decrease was found, 2 internal error (bad JSON, git failure).

Stdlib only -- no network access.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_PATH = "quality-gates.json"
DEFAULT_BASE_REF = "origin/main"


class ThresholdGuardError(Exception):
    """Internal/setup error, distinct from a guard failure verdict."""


def _read_json_at_ref(ref: str, path: str) -> dict[str, Any] | None:
    """Return the parsed JSON content of `path` at `ref`, or None if the
    file does not exist at that ref (e.g. a brand-new file)."""
    result = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ThresholdGuardError(f"{ref}:{path} is not valid JSON: {exc}") from exc


def _read_json_from_disk(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise ThresholdGuardError(f"file not found: {path}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ThresholdGuardError(f"{path} is not valid JSON: {exc}") from exc


def _flatten(section: str, node: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Flatten `{package: {metric: value, ...}}` to `{"section/package": {...}}`."""
    out: dict[str, dict[str, Any]] = {}
    for pkg, metrics in node.items():
        if not isinstance(metrics, dict):
            raise ThresholdGuardError(f"{section}.{pkg} must be an object of metrics")
        out[f"{section}/{pkg}"] = metrics
    return out


def _numeric_metrics(entry: dict[str, Any]) -> dict[str, float]:
    return {k: v for k, v in entry.items() if isinstance(v, (int, float))}


def diff_thresholds(
    old: dict[str, Any] | None, new: dict[str, Any]
) -> list[str]:
    """Compare the `coverage` and `bundleSize` sections of `old` (may be None
    for a brand-new file) against `new`. Returns a list of human-readable
    un-amended-decrease violation messages (empty when clean)."""
    if old is None:
        return []

    old_flat: dict[str, dict[str, Any]] = {}
    new_flat: dict[str, dict[str, Any]] = {}
    for section in ("coverage", "bundleSize"):
        old_flat.update(_flatten(section, old.get(section, {})))
        new_flat.update(_flatten(section, new.get(section, {})))

    violations: list[str] = []
    for key, old_entry in old_flat.items():
        new_entry = new_flat.get(key)
        if new_entry is None:
            # A package dropped entirely from the file is not this guard's
            # concern (it may legitimately be removed by its owning ticket);
            # coverage_gate.py's own missing-artifact handling covers that.
            continue
        amendment = new_entry.get("amendment")
        old_metrics = _numeric_metrics(old_entry)
        new_metrics = _numeric_metrics(new_entry)
        for metric, old_value in old_metrics.items():
            new_value = new_metrics.get(metric)
            if new_value is None:
                continue
            # bundleSize.limitBytes is a *ceiling*: a smaller number is a
            # tightening, not a relaxation. Every other numeric metric here
            # (coverage lines/branches, size regressionPct) is a floor.
            is_ceiling = metric in {"limitBytes"}
            decreased = new_value < old_value if not is_ceiling else new_value > old_value
            if decreased and not amendment:
                violations.append(
                    f"{key}.{metric} decreased from {old_value} to {new_value} "
                    f"without an \"amendment\" reference (C-9.4)"
                )
    return violations


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", default=DEFAULT_PATH, help="Path to quality-gates.json")
    parser.add_argument(
        "--base-ref",
        default=DEFAULT_BASE_REF,
        help="Git ref to diff against (default: origin/main)",
    )
    parser.add_argument(
        "--old-path",
        default=None,
        help="Compare against this file on disk instead of a git ref (used by the negative-test harness)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        old = (
            _read_json_from_disk(args.old_path)
            if args.old_path is not None
            else _read_json_at_ref(args.base_ref, args.path)
        )
        new = _read_json_from_disk(args.path)
    except ThresholdGuardError as exc:
        print(f"threshold-guard configuration error: {exc}", file=sys.stderr)
        return 2

    violations = diff_thresholds(old, new)
    if violations:
        print("threshold-guard: FAIL (C-9.4 -- floors may never be lowered without an amendment)")
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        return 1

    print("threshold-guard: OK -- no un-amended threshold decrease vs " + args.base_ref)
    return 0


if __name__ == "__main__":
    sys.exit(main())
