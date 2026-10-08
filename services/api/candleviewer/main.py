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

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI

from candleviewer.app import AppContext, Supervisor, create_app, load_kline_policy
from candleviewer.observability.logging import configure_logging
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_server import MetricsRuntime
from candleviewer.settings import Settings
from candleviewer.storage.repositories.recorder_sqlalchemy import SqlAlchemyRecorderRepository

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


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


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
        logger().error(
            "boot binding self-check failed (%s): %s — starting in read-only mode",
            ctx.oms_read_only_gate.reason_code,
            ctx.oms_read_only_gate.reason_text,
        )
    else:
        logger().info("boot binding self-check passed; all listening sockets are mesh-only")

    # Hourly re-check (AC5 "drift after resume is caught").
    ctx.mesh_self_check.start()
    scrub_task = getattr(app.state, "scrub_task", None)
    if scrub_task is not None:
        scrub_task.start()
    rule_prune = getattr(app.state, "rule_prune_task", None)
    if rule_prune is not None:
        rule_prune.start()
    funding_task = getattr(app.state, "funding_refresh_task", None)
    if funding_task is not None:
        funding_task.start()
    bars_runtime = getattr(app.state, "bars_runtime", None)
    if bars_runtime is not None:
        await bars_runtime.start()
    kline_boundary = getattr(app.state, "kline_boundary", None)
    if kline_boundary is not None:  # #2060: load the klines hot window; failure keeps 90 d
        _pg = getattr(app.state, "health_pg", None)
        await load_kline_policy(
            kline_boundary, SqlAlchemyRecorderRepository(_pg) if _pg is not None else None
        )
    alert_tasks = [
        t
        for t in (
            getattr(app.state, "alert_purge_task", None),
            getattr(app.state, "alert_gauge_task", None),
        )
        if t is not None
    ]
    for t in alert_tasks:
        t.start()
    overrides = getattr(app.state, "log_level_overrides", None)
    if overrides is not None:
        overrides.start()
    health_registry = getattr(app.state, "health_registry", None)
    if health_registry is not None:
        health_registry.start()
    metrics_runtime: MetricsRuntime | None = None
    if ctx.settings.metrics_enabled:
        # E04-T06: create_app() owns the single facade (telemetry series hang
        # off it); fall back for apps built without one.
        facade = getattr(app.state, "metrics_facade", None)
        if facade is None:
            facade = Metrics(
                ctx.settings.environment.value,
                registry=ctx.metrics,
                process_collectors=True,
            )
        facade.add_process_collectors()
        metrics_runtime = MetricsRuntime(facade, ctx.settings.metrics_bind)
        metrics_runtime.start()
    try:
        yield
    finally:
        if metrics_runtime is not None:
            await metrics_runtime.stop()
        if health_registry is not None:
            await health_registry.stop()
        health_pg = getattr(app.state, "health_pg", None)
        if health_pg is not None:
            await health_pg.dispose()
        if overrides is not None:
            await overrides.stop()
        if rule_prune is not None:
            await rule_prune.stop()
        if funding_task is not None:
            await funding_task.stop()
        for t in alert_tasks:
            await t.stop()
        if scrub_task is not None:
            await scrub_task.stop()
        if bars_runtime is not None:
            await bars_runtime.stop()  # set before writer; both before storage stops
        await ctx.mesh_self_check.stop()
        await supervisor.stop_all()


app = create_app()
app.router.lifespan_context = _lifespan
