"""ASGI entrypoint (`uvicorn candleviewer.main:app`).

Wires the module supervisor into the FastAPI lifespan so `start_all()`/
`stop_all()` run around the server's lifetime (Sec.6.2). Not exercised by
unit tests (which call `create_app()` directly with fakes); covered by
E02-T08's compose smoke test.

E09-T04: the boot binding self-check (AC1/AC3) and the hourly re-check
scheduler (AC5) are started here, not in `create_app()`, so a unit test that
only calls `create_app()` (E02-T05 acceptance criterion 3: no I/O) never
enumerates real sockets — only the ASGI lifespan, which is this module's own
concern, does that.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from candleviewer.app import AppContext, Supervisor, create_app

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    ctx: AppContext = app.state.app_context
    supervisor = Supervisor(ctx)
    await supervisor.start_all()

    # Boot self-check (AC1 "safe binding passes", AC3 "public binding
    # degrades"): run once, synchronously, before serving so `net_binding_safe`
    # and the read-only gate reflect reality from the very first request.
    await ctx.mesh_self_check.run_once()
    if ctx.oms_read_only_gate.is_read_only:
        logger.error(
            "boot binding self-check failed (%s): %s — starting in read-only mode",
            ctx.oms_read_only_gate.reason_code,
            ctx.oms_read_only_gate.reason_text,
        )
    else:
        logger.info("boot binding self-check passed; all listening sockets are mesh-only")

    # Hourly re-check (AC5 "drift after resume is caught").
    ctx.mesh_self_check.start()
    try:
        yield
    finally:
        await ctx.mesh_self_check.stop()
        await supervisor.stop_all()


app = create_app()
app.router.lifespan_context = _lifespan
