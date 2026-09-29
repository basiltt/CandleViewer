"""Static lint for `infra/scripts/pg_bootstrap.sql` (bug #1556 follow-up):
pure text checks, no `psql`/docker needed, that guard against the
non-interactive `psql -f` syntax error this bug fixed (backtick shell
substitution inside `\\set`, which `psql -f` does not always resolve the
same way as an interactive session).
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SQL_PATH = _REPO_ROOT / "infra" / "scripts" / "pg_bootstrap.sql"

_SET_LINE_RE = re.compile(r"^\s*\\set\s+\w+\s+.+$")
_IF_EXISTS_RE = re.compile(r"^\s*\\if\s+:\{\?\w+\}\s*$")


def _lines() -> list[str]:
    return _SQL_PATH.read_text(encoding="utf-8").splitlines()


def test_pg_bootstrap_sql_file_exists() -> None:
    assert _SQL_PATH.is_file(), f"missing {_SQL_PATH}"


def test_pg_bootstrap_sql_has_no_backtick_shell_substitution() -> None:
    """Backtick shell command-substitution inside a `\\set` directive is what
    broke non-interactive `psql -f` invocations (bug #1556); it must never
    come back. Backticks in prose comments (markdown code spans) are fine —
    only executable `\\set` lines are checked."""
    for line in _lines():
        stripped = line.strip()
        if stripped.startswith("--") or not stripped.startswith("\\set"):
            continue
        assert "`" not in stripped, (
            f"\\set line uses backtick shell substitution (psql -f syntax "
            f"error, bug #1556): {line!r}"
        )


def test_pg_bootstrap_sql_set_lines_match_allowed_grammar() -> None:
    """Every `\\set` statement must be a plain literal assignment
    (`\\set name 'value'` or `\\set name value`), never a backtick or
    unquoted shell/command form."""
    for line in _lines():
        stripped = line.strip()
        if not stripped.startswith("\\set"):
            continue
        assert _SET_LINE_RE.match(stripped), f"unexpected \\set grammar: {line!r}"
        assert "`" not in stripped, f"\\set line uses backtick substitution: {line!r}"


def test_pg_bootstrap_sql_every_if_exists_guard_has_matching_endif() -> None:
    """Every `\\if :{?var}` variable-existence guard must be closed by a
    matching `\\endif`, with balanced nesting."""
    depth = 0
    for line in _lines():
        stripped = line.strip()
        if stripped.startswith("\\if"):
            assert _IF_EXISTS_RE.match(stripped), (
                f"\\if guard must be a pure variable-existence check "
                f"(\\if :{{?var}}), not a shell/command condition: {line!r}"
            )
            depth += 1
        elif stripped.startswith("\\endif"):
            depth -= 1
            assert depth >= 0, "unmatched \\endif with no preceding \\if"
    assert depth == 0, "unbalanced \\if / \\endif pairs in pg_bootstrap.sql"


def test_pg_bootstrap_sql_declares_owner_app_ro_password_fallbacks() -> None:
    text = _SQL_PATH.read_text(encoding="utf-8")
    for var in ("owner_pw", "app_pw", "ro_pw"):
        assert f":{{?{var}}}" in text, f"missing \\if :{{?{var}}} guard for {var}"
        assert f"\\set {var} 'CHANGE_ME'" in text, f"missing CHANGE_ME fallback for {var}"
