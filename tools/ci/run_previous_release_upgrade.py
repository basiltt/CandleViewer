#!/usr/bin/env python3
"""E03-T10 CI-MIG-004: verify `alembic upgrade head` succeeds starting from
the previous release tag's schema snapshot, not just a greenfield (empty)
database.

Schema snapshots are published at each release tag as `schema/<tag>.sql`
(ticket "Technical notes / design"). Sprint 01 has not cut a release yet, so
there is no previous-release snapshot to restore — this script detects that
and exits 0 with a clear message rather than failing a check that has
nothing to verify. Once the first release tag lands, its snapshot appears
under `schema/` and this script restores it into the throwaway service
container and runs `alembic upgrade head` against it.

Stdlib + psycopg only (already an `services/api` dependency); no network
beyond the CI-local Postgres service container.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _to_psql_dsn(dsn: str, root: Path) -> str:
    """Normalise any SQLAlchemy-style driver suffix (`+asyncpg`, `+psycopg`,
    ...) to the plain `postgresql://` form `psql` accepts, reusing the single
    source of truth in `candleviewer.migrations.boot` instead of an ad-hoc
    string replace that only handled `+asyncpg`."""
    sys.path.insert(0, str(root))
    from candleviewer.migrations.boot import to_asyncpg_dsn

    return to_asyncpg_dsn(dsn)


def _latest_snapshot(schema_dir: Path) -> Path | None:
    if not schema_dir.is_dir():
        return None
    snapshots = sorted(schema_dir.glob("*.sql"))
    return snapshots[-1] if snapshots else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."), help="services/api root")
    parser.add_argument("--dsn", required=True, help="postgresql+asyncpg:// DSN for the CI Postgres service")
    parser.add_argument(
        "--schema-dir",
        type=Path,
        default=None,
        help="Directory of release schema snapshots (default: <root>/schema)",
    )
    args = parser.parse_args(argv)

    root: Path = args.root
    schema_dir = args.schema_dir or (root / "schema")
    snapshot = _latest_snapshot(schema_dir)

    if snapshot is None:
        # TODO(E03-T10 follow-up): turn this into a hard failure once the
        # first release tag exists and schema/<tag>.sql is published — a
        # perpetual "nothing to verify" pass must not survive past that.
        print(
            "::notice::CI-MIG-004: no previous-release schema snapshot found "
            f"under {schema_dir} yet (no release tag has been cut) — this "
            "check is vacuous until the first release publishes "
            "schema/<tag>.sql; see the TODO in this script for the follow-up"
        )
        return 0

    sync_dsn = _to_psql_dsn(args.dsn, root)
    restore = subprocess.run(
        ["psql", sync_dsn, "-v", "ON_ERROR_STOP=1", "-f", str(snapshot)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if restore.returncode != 0:
        print(f"CI-MIG-004: failed to restore snapshot {snapshot}: {restore.stderr}", file=sys.stderr)
        return 1

    upgrade = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if upgrade.returncode != 0:
        print(
            f"CI-MIG-004: 'alembic upgrade head' failed from previous-release "
            f"schema {snapshot.name}: {upgrade.stderr}",
            file=sys.stderr,
        )
        return 1

    print(f"CI-MIG-004: upgrade from {snapshot.name} succeeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
