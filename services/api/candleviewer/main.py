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
from candleviewer.observability.logging import configure_logging
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_server import MetricsRuntime
from candleviewer.settings import Settings

# E04-T01: logging must be configured before anything else logs a line, and
# exactly once per process (`configure_logging()`'s own docstring). Every
# worker entrypoint (ingestion/recorder/replay) added by later tickets must
# call this the same way, at the top of its own `main.py`.
_settings = Settings()
configure_logging(
    env=_settings.environment.value,
    level=_settings.log_level,
    fmt=_settings.log_format,
)

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
    overrides = getattr(app.state, "log_level_overrides", None)
    if overrides is not None:
        overrides.start()
    metrics_runtime: MetricsRuntime | None = None
    if ctx.settings.metrics_enabled:
        metrics_runtime = MetricsRuntime(
            Metrics(
                ctx.settings.environment.value,
                registry=ctx.metrics,
                process_collectors=True,
            ),
            ctx.settings.metrics_bind,
        )
        metrics_runtime.start()
    try:
        yield
    finally:
        if metrics_runtime is not None:
            await metrics_runtime.stop()
        if overrides is not None:
            await overrides.stop()
        await ctx.mesh_self_check.stop()
        await supervisor.stop_all()


app = create_app()
app.router.lifespan_context = _lifespan
