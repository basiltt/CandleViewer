"""Production composition of the QuestDB ILP writer (#1701).

`build_hot_tier_writer` is the single place that attaches the PG-wire
readiness probe and committed-row counter, so no caller can build an
unguarded writer by accident. `run_reconcile_loop` periodically compares
rows sent vs committed and exports the gap as `questdb_ilp_unreconciled_rows`
(alert on > 0 sustained).
"""

from __future__ import annotations

import asyncio

from candleviewer.observability.metrics import Metrics
from candleviewer.storage.questdb.ilp_writer import IlpTransport, IlpWriter, TableSchema
from candleviewer.storage.questdb.reader import (
    PgWireConnection,
    pgwire_committed_counter,
    pgwire_readiness_probe,
)


def build_hot_tier_writer(
    transport: IlpTransport,
    schemas: dict[str, TableSchema],
    connection: PgWireConnection,
    **kwargs: object,
) -> IlpWriter:
    """`IlpWriter` with readiness probe + committed counter always wired.
    The counter is `count()` over every schema table: it MUST be cumulative
    (monotonic) — `IlpWriter` baselines it once at first connect."""
    return IlpWriter(
        transport,
        schemas,
        readiness_probe=pgwire_readiness_probe(connection),
        committed_counter=pgwire_committed_counter(connection, tuple(schemas)),
        **kwargs,  # type: ignore[arg-type]  # forwarded tuning knobs (max_queue_rows, ...)
    )


async def run_reconcile_loop(
    writer: IlpWriter,
    metrics: Metrics,
    *,
    interval_s: float = 30.0,
    iterations: int | None = None,
) -> None:
    """Every `interval_s`, reconcile and set the gap gauge. Probe failures are
    counted, never fatal. `iterations` bounds the loop for tests."""
    gap_gauge = metrics.gauge(
        "questdb_ilp_unreconciled_rows",
        "ILP rows sent but not (yet) committed per QuestDB count().",
    ).child()
    errors = metrics.counter(
        "questdb_ilp_reconcile_errors_total", "Failed sent-vs-committed reconcile attempts."
    ).child()
    done = 0
    while iterations is None or done < iterations:
        await asyncio.sleep(interval_s)
        try:
            await writer.reconcile()
            gap_gauge.set(writer.unreconciled_rows)
        except Exception:
            errors.inc()
        done += 1
