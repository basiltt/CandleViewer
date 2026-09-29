"""Pure-string Postgres DSN helpers with NO third-party imports.

Split out of `boot.py` (E03-T10 fix) so `tools/ci/run_previous_release_upgrade.py`
can import these helpers when invoked with the system `python` (no `uv run`,
no venv, no asyncpg installed) while `boot.py` — which does need asyncpg for
the advisory-lock connection — re-exports them for its own callers and for
existing tests. Keep this module free of any import beyond the standard
library so it stays importable in that constrained environment.
"""

from __future__ import annotations

import re

_SCHEME_RE = re.compile(r"^postgres(?:ql)?(?:\+[a-z0-9_]+)?://")
# Matches the `user:pass@` (or bare `user@`) credential segment of any DSN
# that may appear verbatim in alembic/psycopg driver error text on stderr.
_DSN_CREDENTIALS_RE = re.compile(r"://[^/@\s]+@")


def redact_dsn_credentials(text: str) -> str:
    """Strip `user:pass@`/`user@` DSN credentials from arbitrary text (e.g.
    subprocess stderr) before it is logged or embedded in an exception
    message (C-12.6 — never let a secret reach a log/exception)."""
    return _DSN_CREDENTIALS_RE.sub("://***@", text)


def to_sync_dsn(dsn: str) -> str:
    """Rewrite any Postgres DSN to the sync psycopg 3 driver Alembic uses."""
    return _SCHEME_RE.sub("postgresql+psycopg://", dsn, count=1)


def to_asyncpg_dsn(dsn: str) -> str:
    """Rewrite any Postgres DSN to the plain form `asyncpg.connect` accepts."""
    return _SCHEME_RE.sub("postgresql://", dsn, count=1)
