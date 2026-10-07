from __future__ import annotations

from typing import Any

from candleviewer.ws.bar_coalescer import BarCoalescer


def _bar(gen: int, idx: int, c: str, *, confirm: bool = False, **kw: Any) -> dict[str, Any]:
    return {"generation": gen, "index": idx, "t_ms": 1000, "c": c, "confirm": confirm, **kw}


def test_same_t_ms_volume_bars_are_not_merged() -> None:
    co = BarCoalescer()
    for i in range(5):
        co.add(_bar(0, i, str(i), confirm=True))
    items, count = co.flush()
    assert [b["index"] for b in items] == [0, 1, 2, 3, 4]
    assert count == 5


def test_coalesced_state_equals_applying_every_update() -> None:
    updates = [_bar(0, 0, "1"), _bar(0, 0, "2"), _bar(0, 1, "5"), _bar(0, 0, "3", confirm=True)]
    full: dict[tuple[int, int], dict[str, Any]] = {}
    for u in updates:
        full[(u["generation"], u["index"])] = u
    co = BarCoalescer()
    for u in updates:
        co.add(u)
    items, count = co.flush()
    assert {(b["generation"], b["index"]): b for b in items} == full
    assert count == 4


def test_generation_is_part_of_key() -> None:
    co = BarCoalescer()
    co.add(_bar(0, 0, "1"))
    co.add(_bar(1, 0, "2"))
    assert len(co.flush()[0]) == 2


def test_unconfirmed_never_replaces_confirmed() -> None:
    co = BarCoalescer()
    co.add(_bar(0, 0, "1", confirm=True))
    co.add(_bar(0, 0, "2"))
    assert co.flush()[0][0]["c"] == "1"


def test_confirmed_replaced_only_when_amended() -> None:
    co = BarCoalescer()
    co.add(_bar(0, 0, "1", confirm=True))
    co.add(_bar(0, 0, "2", confirm=True))
    assert co.flush()[0][0]["c"] == "1"
    co.add(_bar(0, 0, "1", confirm=True))
    co.add(_bar(0, 0, "9", confirm=True, amended=True))
    assert co.flush()[0][0]["c"] == "9"


def test_overflow_flags_resnapshot() -> None:
    co = BarCoalescer(max_pending=1)
    co.add(_bar(0, 0, "1"))
    co.add(_bar(0, 1, "1"))
    assert co.overflowed
