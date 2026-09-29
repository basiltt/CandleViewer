#!/usr/bin/env python3
"""E03-T04: apply ratchet proposals (package -> new baseline) produced by
`coverage_gate.py --ratchet --ratchet-out <file>` to
`tools/ci/coverage-baselines.json`, in place.

Only ever raises a `baseline` value (never lowers one — a proposal whose
value is not strictly greater than the current baseline is ignored, which
should never happen given `compute_ratchet_proposals`'s own >=1pp-increase
requirement, but this guard keeps the invariant true even if a stale/hand-
edited proposals file is fed in). Writes GitHub Actions `changed` and
`summary` outputs (via `$GITHUB_OUTPUT` when set, else stdout) so the
calling workflow step can decide whether to open a PR.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def apply_proposals(proposals: dict[str, float], baselines_path: Path) -> list[str]:
    """Mutate the baselines file in place. Returns a list of
    human-readable "package: old% -> new%" change lines (empty if
    nothing changed)."""
    config = json.loads(baselines_path.read_text(encoding="utf-8"))
    changes: list[str] = []

    for package, new_baseline in proposals.items():
        pkg_cfg = config["packages"].get(package)
        if pkg_cfg is None:
            continue
        old_baseline = float(pkg_cfg["baseline"])
        if new_baseline <= old_baseline:
            continue
        pkg_cfg["baseline"] = new_baseline
        changes.append(f"{package}: {old_baseline:.1f}% -> {new_baseline:.1f}%")

    if changes:
        baselines_path.write_text(
            json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    return changes


def _write_github_output(name: str, value: str) -> None:
    gh_output = os.environ.get("GITHUB_OUTPUT")
    if not gh_output:
        print(f"{name}={value}")
        return
    with open(gh_output, "a", encoding="utf-8") as fh:
        if "\n" in value:
            fh.write(f"{name}<<EOF\n{value}\nEOF\n")
        else:
            fh.write(f"{name}={value}\n")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print(
            "usage: apply_ratchet_proposals.py <proposals.json> <coverage-baselines.json>",
            file=sys.stderr,
        )
        return 2

    proposals_path, baselines_path = Path(argv[0]), Path(argv[1])
    if not proposals_path.is_file():
        # No proposals file (e.g. the gate step failed before ever
        # producing one) -> nothing to do, not an error.
        _write_github_output("changed", "false")
        _write_github_output("summary", "no ratchet proposals file found")
        return 0

    proposals = json.loads(proposals_path.read_text(encoding="utf-8"))
    changes = apply_proposals(proposals, baselines_path)

    _write_github_output("changed", "true" if changes else "false")
    summary = (
        "\n".join(f"- {c}" for c in changes) if changes else "no packages ratcheted"
    )
    _write_github_output("summary", summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
