"""#2053: stored-tape lookup failures become a refusal, never a write."""

from __future__ import annotations

import asyncio

import pytest

from candleviewer.bars.kline_rows import (
    PrecedenceHealth,
    TapePrecedenceUnknown,
    bars_kline_refused_total,
    guarded_tape_lookup,
    kline_spec,
    submit_kline_bars,
)
from candleviewer.bars.rows import BarPersistError
from candleviewer.bars.writer import BarWriter
from tests.unit.bars.test_kline_rows import T0, W5, _k  # type: ignore[attr-defined]


class _Sink:
    async def write_rows(self, table: str, rows: list[dict[str, object]], ts_us_key: str) -> None:
        return None


def _writer() -> BarWriter:
    return BarWriter(_Sink())


def _count() -> float:
    return bars_kline_refused_total.labels("precedence_unknown")._value.get()


async def _raise_oserror(s: str, p: str, t: list[int]) -> set[int]:
    raise OSError("conn reset")


async def _hang(s: str, p: str, t: list[int]) -> set[int]:
    await asyncio.sleep(10)
    return set()


def test_error_is_a_bar_persist_error() -> None:
    assert issubclass(TapePrecedenceUnknown, BarPersistError)


@pytest.mark.parametrize("lookup", [_raise_oserror, _hang])
async def test_lookup_failure_refuses_counts_degrades(lookup) -> None:  # type: ignore[no-untyped-def]
    w, health, before = _writer(), PrecedenceHealth(), _count()
    n = await submit_kline_bars(
        w, "BTCUSDT", "5", [_k(T0), _k(T0 + W5)],
        stored_higher=guarded_tape_lookup(lookup, timeout_s=0.05), health=health,
    )  # fmt: skip
    assert n == 0
    assert w.depth == 0
    assert _count() == before + 2
    assert health.degraded
    assert health.reason() == "tape_precedence_unknown"


async def test_driver_error_is_mapped() -> None:
    class DriverError(Exception): ...

    async def bad(s: str, p: str, t: list[int]) -> set[int]:
        raise DriverError

    with pytest.raises(TapePrecedenceUnknown):
        await guarded_tape_lookup(bad, transient=(DriverError,))("A", "1", [1])


async def test_tape_present_is_refused_as_overwrite_and_absent_is_written() -> None:
    async def present(s: str, p: str, t: list[int]) -> set[int]:
        return set(t)

    async def absent(s: str, p: str, t: list[int]) -> set[int]:
        return set()

    w, health = _writer(), PrecedenceHealth()
    health.degraded = True
    ev = [_k(T0)]
    refused = guarded_tape_lookup(present)
    written = guarded_tape_lookup(absent)
    assert await submit_kline_bars(w, "BTCUSDT", "5", ev, stored_higher=refused, health=health) == 0
    assert await submit_kline_bars(w, "BTCUSDT", "5", ev, stored_higher=written, health=health) == 1
    assert not health.degraded  # a successful lookup clears it


async def test_writer_side_tape_refusal_unchanged() -> None:
    async def absent(s: str, p: str, t: list[int]) -> set[int]:
        return set()

    w = _writer()
    spec = kline_spec("5")
    w._sources[("bars_time", spec.spec_hash + "BTCUSDT", T0)] = "tape"
    assert await submit_kline_bars(w, "BTCUSDT", "5", [_k(T0)], stored_higher=absent) == 0
