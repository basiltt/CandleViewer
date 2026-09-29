"""Single-Alembic-head invariant (`21-database-schema.md` §9 rule 1: "Single
linear history on `main`").

Owned in one dedicated, tip-agnostic file rather than duplicated in every
revision's own test module — each new revision becomes the new tip, which
would otherwise make a per-revision copy of this assertion stale by
construction (see `test_0002_rbac_seed.py`'s docstring history).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_SERVICES_API_ROOT = Path(__file__).resolve().parents[3]


def test_alembic_heads_is_single_revision() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        cwd=_SERVICES_API_ROOT,
        env={**os.environ},
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    heads = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(heads) == 1, f"expected exactly one head, got: {heads!r}"
    assert heads[0].endswith("(head)")
