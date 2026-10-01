"""E04-T06: stage latency is recorded on the real ingestion publish path."""

from __future__ import annotations

import asyncio
import random
from datetime import UTC, datetime
from decimal import Decimal

from candleviewer.app import create_app
from candleviewer.ingestion.synthetic_feed import SyntheticFeedGenerator, SyntheticFeedMetrics
from candleviewer.observability.latency import STAGE_BUCKETS, StageRecorder
from candleviewer.observability.metrics import Metrics


def test_create_app_attaches_recorder_to_ingestion() -> None:
    app = create_app()
    assert isinstance(app.state.app_context.ingestion.latency, StageRecorder)


async def test_publish_records_stage_histograms_with_clock_offset() -> None:
    m = Metrics("demo")
    hist = m.histogram("ingest_stage_seconds", "h", ("stage",), buckets=STAGE_BUCKETS, max_series=4)
    ticks = iter(range(1000, 100000, 3))
    queue: asyncio.Queue = asyncio.Queue(maxsize=8)

    gen = SyntheticFeedGenerator(
        records=[object()],  # type: ignore[list-item]
        queue=queue,
        metrics=SyntheticFeedMetrics(m.registry),
        rate_hz=10,
        rng=random.Random(1),  # noqa: S311
        latency=StageRecorder(hist, 1),
        clock_offset_ms=lambda: 0,
        now_ms=lambda: next(ticks),
    )
    await gen._publish_one(object())  # type: ignore[arg-type]
    n = m.registry.get_sample_value(
        "ingest_stage_seconds_count", {"env": "demo", "stage": "fanout"}
    )
    assert n == 1
    ex = m.registry.get_sample_value(
        "ingest_stage_seconds_count", {"env": "demo", "stage": "exchange"}
    )
    assert ex == 1  # offset provider supplied -> exchange stage available
    _ = (UTC, datetime, Decimal)
