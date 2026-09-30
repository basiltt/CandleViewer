#!/usr/bin/env python3
"""tools/statechart/check_machine_hash_lock.py — E50-T02.

CI-blocking gate: diffs the currently-loaded machine registry's
`machine_hash` values against the committed
`services/api/candleviewer/statechart/machines/machine_hashes.lock`.

  * A brand-new machine (no lock entry yet) is fine; run with `--write` to
    add it to the lock file (used locally / by the same PR that adds it).
  * A machine whose hash changed with no chart `version` bump AND no
    registered upcaster (`candleviewer.statechart.upcasters`) for that
    exact hash transition fails the build, naming the machine
    (ticket acceptance criterion 1, MUST-12/MUSTNOT-09).
  * A machine removed from the registry but still in the lock file fails
    too (`--allow-removed` opts out for the PR that deliberately retires a
    machine, mirroring `tools/ci/verify_migration_lockfile.py`'s
    `--no-base-check` escape hatch).

Usage:
    python tools/statechart/check_machine_hash_lock.py [--write]
        [--machines-dir DIR] [--lock-path PATH] [--allow-removed]

Exit codes: 0 clean (or written), 1 uncovered drift / removed-machine
violation, 2 internal error (bad lock JSON, bad machines dir).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_API_ROOT = _REPO_ROOT / "services" / "api"


def _sys_path_for_api() -> None:
    api_str = str(_API_ROOT)
    if api_str not in sys.path:
        sys.path.insert(0, api_str)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--machines-dir",
        type=Path,
        default=None,
        help="Directory of *.machine.json files (default: the package's own machines/).",
    )
    parser.add_argument(
        "--lock-path",
        type=Path,
        default=None,
        help="Path to machine_hashes.lock (default: alongside --machines-dir).",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the current registry state to the lock file instead of diffing.",
    )
    parser.add_argument(
        "--allow-removed",
        action="store_true",
        help="Do not fail on a machine present in the lock file but no longer registered.",
    )
    args = parser.parse_args(argv)

    _sys_path_for_api()
    from candleviewer.statechart.lock import (
        LockFileError,
        check_removed,
        diff,
        load_lock,
        render_lock,
    )
    from candleviewer.statechart.registry import DEFAULT_MACHINES_DIR, Registry

    machines_dir = args.machines_dir or DEFAULT_MACHINES_DIR
    lock_path = args.lock_path or (machines_dir / "machine_hashes.lock")

    try:
        registry = Registry(machines_dir=machines_dir)
    except Exception as exc:  # noqa: BLE001 - surfaced verbatim, this is a CLI
        print(f"error: could not load machine registry: {exc}", file=sys.stderr)
        return 2

    if args.write:
        rendered = render_lock(registry)
        lock_path.write_text(
            json.dumps(rendered, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {lock_path} ({len(rendered['machines'])} machine(s))")
        return 0

    try:
        locked = load_lock(lock_path)
    except LockFileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    findings = diff(registry, locked)
    uncovered = [f for f in findings if not f.covered]
    covered = [f for f in findings if f.covered]

    for f in covered:
        print(f"OK (covered): {f.format()}")

    if uncovered:
        print("machine-hash-lock: uncovered hash drift found:", file=sys.stderr)
        for f in uncovered:
            print(f"  {f.format()}", file=sys.stderr)

    removed = [] if args.allow_removed else check_removed(registry, locked)
    if removed:
        print(
            "machine-hash-lock: machine(s) in machine_hashes.lock no longer "
            "registered (pass --allow-removed if this retirement is deliberate): "
            + ", ".join(removed),
            file=sys.stderr,
        )

    if uncovered or removed:
        return 1

    print(f"OK: {len(registry.keys())} machine(s) verified against {lock_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
