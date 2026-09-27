"""ASGI entrypoint (`uvicorn candleviewer.main:app`).

Wires the module supervisor into the FastAPI lifespan so `start_all()`/
`stop_all()` run around the server's lifetime (Sec.6.2). Not exercised by
unit tests (which call `create_app()` directly with fakes); covered by
E02-T08's compose smoke test.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from candleviewer.app import Supervisor, create_app


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    supervisor = Supervisor(app.state.app_context)
    await supervisor.start_all()
    try:
        yield
    finally:
        await supervisor.stop_all()


app = create_app()
app.router.lifespan_context = _lifespan
