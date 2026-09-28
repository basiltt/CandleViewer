#!/usr/bin/env python3
"""E03-T04: flatten per-package coverage reports into the single
`<artifact-dir>/<artifact-name>/{coverage.xml,lcov.info}` layout that
`tools/ci/coverage_gate.py` expects by default.

The JS/engine lanes (`_job-js.yml`, E03-T02) upload one shared artifact
(`coverage-unit-frontend`, `coverage-unit-engine`) containing several
packages' `lcov.info` files at their original repo-relative paths, e.g.:

    coverage-unit-frontend/apps/web/coverage/lcov.info
    coverage-unit-frontend/apps/desktop/coverage/lcov.info
    coverage-unit-frontend/packages/ui/coverage/lcov.info

`coverage-baselines.json` maps each package name (e.g. `"apps/app-web"`) to
the artifact it lives in, and `coverage_gate.py` looks for
`<report-dir>/<artifact>/lcov.info` by default. This script copies each
matching per-package `lcov.info` to `<report-dir>/<artifact>/lcov.info`
using the package's own coverage-baselines.json entry, so no path mapping
is duplicated between this script and the baselines file.

Package name -> on-disk directory mapping (only needed because
`apps/app-web` / `apps/app-electron` are the ticket's package names but the
repo directories are `apps/web` / `apps/desktop` — see
`docs/plan/20-architecture.md` §5 repo map vs. this ticket's Scope /
Deliverables list, which names the floors by the ticket's own package
labels). `services/api`, `packages/chart-engine`, `packages/protocol` and
`packages/ui` already match their repo directories 1:1.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PACKAGE_TO_REPO_DIR: dict[str, str] = {
    "apps/app-web": "apps/web",
    "apps/app-electron": "apps/desktop",
}


def _repo_dir_for(package: str) -> str:
    return _PACKAGE_TO_REPO_DIR.get(package, package)


def flatten(report_dir: Path) -> list[Path]:
    """Copy each package's `coverage/lcov.info` into
    `<report_dir>/<artifact>/lcov.info` if it isn't already there
    (services/api's `coverage.xml` is already uploaded flat by `_job-py.yml`
    and needs no flattening). Returns the list of files written."""
    import json

    baselines_path = Path(__file__).parent / "coverage-baselines.json"
    config = json.loads(baselines_path.read_text(encoding="utf-8"))
    written: list[Path] = []

    for package, cfg in config["packages"].items():
        if cfg["report_format"] != "lcov":
            continue
        artifact = cfg["artifact"]
        dest = report_dir / artifact / "lcov.info"
        if dest.is_file():
            continue  # already flat (e.g. a single-package artifact)

        repo_dir = _repo_dir_for(package)
        source = report_dir / artifact / repo_dir / "coverage" / "lcov.info"
        if not source.is_file():
            continue  # coverage_gate.py will report CI-COV-003 for this one

        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(source.read_bytes())
        written.append(dest)

    return written


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    report_dir = Path(argv[0]) if argv else Path("coverage-artifacts")
    written = flatten(report_dir)
    for path in written:
        print(f"flattened -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
