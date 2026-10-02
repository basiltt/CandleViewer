"""B14 `book` health chart driven through the factory with a BookEngine runtime
(E08-S05). The per-delta path never reaches the interpreter (INV-B14-a)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from xstate_statemachine import SimulatedClock

from candleviewer.book.models import BookPhase
from candleviewer.book.resync import BookEngine
from candleviewer.statechart import build
from candleviewer.statechart.bindings import b14_book as b14
from tests.unit.book._builders import delta, lvl, snap


class _Sup:
    def __init__(self, interp: object) -> None:
        self.interp = interp
        self.sent: list[str] = []

    async def send(self, event: str) -> None:
        self.sent.append(event)
        await self.interp.send(event, wait=True)  # type: ignore[attr-defined]


async def _ids(interp: object) -> set[str]:
    for _ in range(20):
        await asyncio.sleep(0)
    return {s.rsplit(".", 1)[-1] for s in interp.current_state_ids}  # type: ignore[attr-defined]


async def test_b14_supervised_lifecycle_and_hot_path_bypass() -> None:
    out: list[object] = []

    async def pub(ev: object) -> None:
        out.append(ev)

    async def resub() -> None: ...

    e = BookEngine(symbol="BTCUSDT", depth=200, publish=pub, resubscribe=resub, now_us=lambda: 0)
    b14.register_runtime("bk1", e)
    try:
        r = await build("book", ctx={"book_key": "bk1"}, clock=SimulatedClock(), lane="platform")
        sup = _Sup(r.interpreter)
        e.supervisor = sup
        await e.start()
        assert "snapshot_pending" in await _ids(r.interpreter)
        assert e.phase is BookPhase.SNAPSHOT_PENDING
        await e.on_event(snap(10, [lvl(99, 1)], [lvl(101, 1)]))
        assert "live" in await _ids(r.interpreter) and e.phase is BookPhase.LIVE
        for u in range(11, 20):
            await e.on_event(delta(u, u - 1, [lvl(99, u)]))
        assert "DELTA" not in sup.sent  # INV-B14-a
        await e.on_event(delta(30, 25))
        assert "snapshot_pending" in await _ids(r.interpreter)
        assert e.phase is BookPhase.SNAPSHOT_PENDING and e.resync_count == 1
        assert r.interpreter.context["resync_count"] == 1
        await r.interpreter.stop()
    finally:
        b14.unregister_runtime("bk1")


async def test_b14_without_runtime_is_inert() -> None:
    r = await build("book", ctx={"book_key": "none"}, clock=SimulatedClock(), lane="platform")
    await r.interpreter.send("SUBSCRIBE", wait=True)
    await r.interpreter.send("SNAPSHOT_TIMEOUT", wait=True)
    assert "snapshot_pending" in await _ids(r.interpreter)
    await r.interpreter.stop()


def test_book_hot_path_never_imports_statechart() -> None:
    """CV-LINT-HOTPATH fixture: book/*.py has no statechart import."""
    root = Path(__file__).resolve().parents[2] / "candleviewer" / "book"
    for f in root.glob("*.py"):
        text = f.read_text(encoding="utf-8")
        assert "candleviewer.statechart" not in text and "xstate_statemachine" not in text, f
