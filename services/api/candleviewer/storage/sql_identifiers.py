"""Identifier validation for SQL that cannot use bound parameters.

Bound parameters carry *values*, never identifiers: DuckDB DDL (`CREATE VIEW`,
`ATTACH`) and QuestDB/Postgres table names in `FROM` cannot be bound. Every
place in `storage/**` that has to splice an identifier into SQL goes through
`checked_identifier` first, so a name that is not a plain SQL identifier is
rejected before any SQL is built (C-12, `cv-storage-sql-construction`).
"""

from __future__ import annotations

import re

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,62}")


class UnsafeSqlIdentifier(ValueError):
    """A name destined for an identifier slot is not a plain SQL identifier."""


def checked_identifier(name: str) -> str:
    """Return `name` unchanged iff it is a plain identifier (letters, digits,
    underscore; not starting with a digit; <=63 chars, the Postgres limit)."""
    if not _IDENTIFIER.fullmatch(name):
        raise UnsafeSqlIdentifier(f"not a plain SQL identifier: {name!r}")
    return name


def sql_string_literal(text: str) -> str:
    """Single-quoted SQL string literal with embedded quotes doubled. Only for
    grammar slots that accept no bind parameter (DuckDB `read_parquet` in DDL,
    `ATTACH`); NUL is rejected because it truncates in some C drivers."""
    if "\x00" in text:
        raise UnsafeSqlIdentifier("NUL byte in SQL literal")
    return "'" + text.replace("'", "''") + "'"
