"""pytest wrapper for the E05-D01 token-proof verifier.

Runs packages/ui/tokens/tests/verify_tokens.py as a subprocess so the same
check that gates local/manual verification also runs under `pytest`, per
CLAUDE.md/AGENTS.md test-first requirement for any new script.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "packages" / "ui" / "tokens" / "tests" / "verify_tokens.py"


def test_token_proof_all_themes_resolve_with_no_unset_variables() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "OK:" in result.stdout
