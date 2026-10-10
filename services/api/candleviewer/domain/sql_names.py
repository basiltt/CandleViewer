"""Pure SQL-name helpers shared by `bars` and `storage` (bars may not import storage, M8).

`storage/sql_identifiers.py` re-exports these so storage code keeps one import site.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,62}")

#: Provenance: QuestDB 8.x docs, questdb.io/docs/reference/sql/reserved-names/.
#: QuestDB keywords that cannot be used as a bare column name (a conservative snapshot of the
#: reserved list in the QuestDB docs; extend, never shrink). The 0004 DDL quotes `"index"` for this
#: reason (#2016); `column_identifier` is the single place SQL text quotes such names.
QUESTDB_RESERVED: frozenset[str] = frozenset(
    "add all alter and as asc asof between by cache capacity case cast column columns copy create "
    "cross database default delete desc distinct drop else end except exists fill foreign from "
    "grant group header if in index inner insert intersect into isolation join key latest left "
    "limit lock lt natural nulls offset on or order outer over partition primary references "
    "rename repair right sample select show splice system table tables then to transaction "
    "truncate type union unlock update values when where with writer".split()
)


def column_identifier(name: str) -> str:
    """A validated column name, double-quoted iff QuestDB reserves it (e.g. `index`)."""
    if not _IDENTIFIER.fullmatch(name):
        raise ValueError(f"not a plain SQL identifier: {name!r}")
    return f'"{name}"' if name.lower() in QUESTDB_RESERVED else name


EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
EPOCH_NAIVE = datetime(1970, 1, 1)


def ts_param(us: int) -> datetime:
    """Epoch microseconds -> NAIVE datetime for a `TIMESTAMP` bind: naive, interpreted as UTC by
    QuestDB's PGWire (its TIMESTAMP is tz-less, so asyncpg's codec rejects an aware datetime).

    Exact to the microsecond (`EPOCH_NAIVE + timedelta`, never a float division).
    """
    if isinstance(us, bool) or not isinstance(us, int):
        raise TypeError("ts_param expects an int (epoch µs)")
    return EPOCH_NAIVE + timedelta(microseconds=us)


def ts_us_from_row(value: object) -> int:
    """A `TIMESTAMP` value read back from QuestDB (datetime) -> epoch microseconds.

    Ints pass through (ILP-shaped rows and test fakes); naive datetimes are taken as UTC.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        delta = value - EPOCH
        return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds
    return int(str(value))


_PLACEHOLDER = re.compile(r"\$(\d+)")


class SqlBindMismatch(ValueError):
    """The SQL's `$n` placeholders and the bind list disagree (caught before the server)."""


def assert_bind_count(sql: str, params: tuple[object, ...] | list[object]) -> None:
    """Raise `SqlBindMismatch` unless the distinct `$n` set is exactly `$1..$len(params)`.

    One O(n) pass over `sql`. QuestDB PGWire does not treat `LIMIT $n` as a bind slot
    (#2168), so such a query shows up here as an extra param.
    """
    found = {int(m) for m in _PLACEHOLDER.findall(sql)}
    expected = set(range(1, len(params) + 1))
    if found != expected:
        raise SqlBindMismatch(
            f"SQL has placeholders {sorted(found)} but {len(params)} bind value(s) were given"
        )
