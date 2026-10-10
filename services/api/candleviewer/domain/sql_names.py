"""Pure SQL-name helpers shared by `bars` and `storage` (bars may not import storage, M8).

`storage/sql_identifiers.py` re-exports these so storage code keeps one import site.
"""

from __future__ import annotations

import re

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,62}")

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
