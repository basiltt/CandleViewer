"""E08-T04: the public WS skeleton is wired into `create_app()` behind
`ingestion_ws_enabled` (default off, C-4.13). No socket is opened here."""

from __future__ import annotations

from candleviewer.app import create_app
from candleviewer.ingestion.connection import ConnectionManager
from candleviewer.ingestion.service import WS_FRAME_QUEUE_MAXSIZE
from candleviewer.settings import Settings


def test_flag_default_off() -> None:
    assert Settings().ingestion_ws_enabled is False


def test_flag_off_manager_not_constructed() -> None:
    app = create_app(Settings(ingestion_ws_enabled=False))
    assert app.state.app_context.ingestion.ws is None


def test_flag_on_manager_constructed_and_owned_by_ingestion() -> None:
    app = create_app(Settings(ingestion_ws_enabled=True))
    ing = app.state.app_context.ingestion
    assert isinstance(ing.ws, ConnectionManager)
    assert ing.ws.state() == "closed"  # supervised: started by the module lifecycle only
    assert ing.ws_frames.maxsize == WS_FRAME_QUEUE_MAXSIZE > 0  # bounded (C-2.18)


def test_frame_queue_overflow_drops_and_counts() -> None:
    ing = create_app(Settings(ingestion_ws_enabled=True)).state.app_context.ingestion
    for _ in range(WS_FRAME_QUEUE_MAXSIZE + 3):
        ing.offer_frame("{}")
    assert ing.ws_frames.qsize() == WS_FRAME_QUEUE_MAXSIZE
    assert ing.ws_frames_dropped == 3


async def test_supervisor_lifecycle_starts_and_stops_ws() -> None:
    app = create_app(Settings(ingestion_ws_enabled=True))
    ing = app.state.app_context.ingestion
    calls: list[str] = []

    class _Fake:
        async def start(self) -> None:
            calls.append("start")

        async def stop(self) -> None:
            calls.append("stop")

    ing.ws = _Fake()
    await ing.start(app.state.app_context)
    await ing.stop(1.0)
    assert calls == ["start", "stop"]
