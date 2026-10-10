"""Explicit golden regeneration for the determinism harness (E12-T04). Never run by CI.

    cd services/api
    uv run python -m bench.bar_determinism.regen_goldens            # dry run: what would change
    uv run python -m bench.bar_determinism.regen_goldens --write --reason "why"

Refuses: under CI (`CI` set); without `--reason`; when a builder kind's output changed but its
`BUILD_VERSIONS` entry was not bumped (the bump and the regenerated files go in one commit).
"""

from __future__ import annotations

import argparse
import os
import sys

from . import goldens


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true", help="write the regenerated golden files")
    ap.add_argument(
        "--reason",
        default=os.environ.get("CV_GOLDEN_REASON", ""),
        help="why the output legitimately changed",
    )
    ap.add_argument(
        "--suite",
        choices=("determinism", "conformance", "all"),
        default="determinism",
        help="which golden bank (E12-T04 determinism day, E12-Q02 conformance tapes, or both)",
    )
    args = ap.parse_args(argv)
    if os.environ.get("CI"):
        print("refused: golden regeneration never runs in CI", file=sys.stderr)
        return 2
    rc = 0
    if args.suite in ("conformance", "all"):
        rc = _conformance(args.write, args.reason)
        if args.suite == "conformance":
            return rc
    return max(rc, _determinism(args.write, args.reason))


def _conformance(write: bool, reason: str) -> int:
    from bench.bar_conformance import bank as cg

    p = cg.build(reason)
    for line in p.summary:
        print(f"conformance: {line}")
    if not p.changed:
        print("conformance goldens are up to date")
        return 0
    print(f"conformance: {len(p.changed)} file(s) differ from the committed bank")
    if not write:
        return 1
    if not reason.strip():
        print("refused: --reason is required", file=sys.stderr)
        return 2
    if p.unbumped:
        print(
            "refused: output changed for "
            + ", ".join(p.unbumped)
            + " but BUILD_VERSIONS (candleviewer/bars/rows.py) was not bumped",
            file=sys.stderr,
        )
        return 2
    cg.write(cg.build(reason.strip()))
    print("wrote the conformance bank; review `git diff --stat` and commit with the bump")
    return 0


def _determinism(write: bool, reason: str) -> int:
    args = argparse.Namespace(write=write, reason=reason)
    p = goldens.plan(goldens.load_tape())
    for label in p.changed:
        print(f"would change: {label}")
    if not p.changed:
        print("goldens are up to date")
        return 0
    if not args.write:
        return 1
    if not args.reason.strip():
        print("refused: --reason is required", file=sys.stderr)
        return 2
    if p.unbumped:
        print(
            "refused: output changed for "
            + ", ".join(p.unbumped)
            + " but BUILD_VERSIONS (candleviewer/bars/rows.py) was not bumped",
            file=sys.stderr,
        )
        return 2
    goldens.write(p, args.reason.strip())
    print(f"wrote {len(p.changed)} golden file(s); commit them with the build_version bump")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
