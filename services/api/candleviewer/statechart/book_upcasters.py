"""B14 `book` snapshot upcaster (#2204, OC-08).

The OC-08 fix added the `max_buffered_deltas` context bound (INV-B14-d). A
snapshot taken at the pre-#2204 hash lacks the key; the upcaster seeds it with
the engine's bound (`book.resync.BUFFER_BOUND`, mirrored as
`b14_book.DEFAULT_MAX_BUFFERED_DELTAS`) and truncates nothing: an old
`buffered_deltas` list longer than the bound is left as-is so the next `DELTA`
trips `delta_buffer_full` and takes the resync path (C-2.5).
"""

from __future__ import annotations

from typing import Any

from candleviewer.statechart.upcasters import register_upcaster

B14_FROM_HASH = "a483e363f64e69f28559ce0e9d3c480e99d7289dbce026aea7a664ad342b8f8d"
B14_TO_HASH = "73121e4a182f168f15289b74f7894db4aaf9432acbb9623ef6adef4c85e8fce4"
B14_MAX_BUFFERED_DELTAS = 1_000


def upcast_book_v0_to_v1(context: dict[str, Any]) -> dict[str, Any]:
    out = dict(context)
    out.setdefault("max_buffered_deltas", B14_MAX_BUFFERED_DELTAS)
    return out


register_upcaster("book", B14_FROM_HASH, B14_TO_HASH, upcast_book_v0_to_v1)
