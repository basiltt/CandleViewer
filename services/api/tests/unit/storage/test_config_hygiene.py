"""Security/config-hygiene tests (E07-T01):

- "Config is read exclusively from M1 ... the package must not call
  `os.environ` directly - checked by a unit test."
- "A unit test asserts `repr(settings.pg_dsn)` contains no password substring."
"""

from __future__ import annotations

import ast
from pathlib import Path

STORAGE_PKG = Path(__file__).resolve().parents[3] / "candleviewer" / "storage"


def _iter_py_files() -> list[Path]:
    return [p for p in STORAGE_PKG.rglob("*.py")]


def test_storage_package_never_calls_os_environ_directly() -> None:
    offenders: list[str] = []
    for path in _iter_py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "environ":
                offenders.append(f"{path}:{node.lineno}")
            if isinstance(node, ast.ImportFrom) and node.module == "os" and any(
                alias.name == "environ" for alias in node.names
            ):
                offenders.append(f"{path}:{node.lineno}")
    assert not offenders, f"os.environ used directly in storage package: {offenders}"


def test_settings_pg_dsn_repr_never_leaks_password() -> None:
    from candleviewer.settings import Settings

    settings = Settings(pg_dsn="postgresql+asyncpg://user:supersecret@host:5432/db")  # type: ignore[arg-type]
    assert "supersecret" not in repr(settings)
    assert "supersecret" not in str(settings)
