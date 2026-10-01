"""Frontend telemetry ingestion (E04-T06, ADR-0014 §2, threat A-17).

Clients push one *pre-bucketed* payload per 10 s per session; the server adds
the bucket counts into its own histograms (histogram-of-histograms — never raw
samples). Defences, all enforced here:

- schema-closed (`extra="forbid"`, strict types, fixed bucket-array lengths);
- `screen` is a sitemap route id (`R-nnn`) — the only label taken from the
  client, further capped by the facade's `max_series`;
- payload byte cap and per-session token bucket (rate);
- every rejection increments `telemetry_rejected_total{reason}` (closed enum)
  and is never logged verbatim; no symbol/account field exists to leak.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from candleviewer.observability.metrics import BoundedMetric, Metrics
from candleviewer.observability.metrics_catalogue import (
    FE_DECODE_BUCKETS,
    FE_FRAME_BUCKETS,
    register_r0,
)

#: Hard cap on request bytes (a valid payload is < 1 KiB).
MAX_PAYLOAD_BYTES: Final = 4096
#: One payload per 10 s per session; burst 2 tolerates timer jitter.
PUSH_INTERVAL_S: Final = 10.0
BURST: Final = 2
#: Upper bound on counts per bucket in one 10 s window (240 fps * 10 s).
MAX_BUCKET_COUNT: Final = 2400
#: Sessions tracked by the limiter (LRU); bounded memory.
MAX_TRACKED_SESSIONS: Final = 256

RejectReason = Literal["too_large", "rate_limited", "invalid", "unauthenticated"]
REJECT_REASONS: Final[tuple[RejectReason, ...]] = (
    "too_large",
    "rate_limited",
    "invalid",
    "unauthenticated",
)

_Count = Annotated[int, Field(ge=0, le=MAX_BUCKET_COUNT, strict=True)]


class BucketCounts(BaseModel):
    """Non-cumulative counts per bucket edge plus one `+Inf` overflow slot."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    counts: list[_Count]


class FrontendTelemetry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    screen: Annotated[str, Field(pattern=r"^R-[0-9]{3}$")]
    engine_version: Annotated[str, Field(pattern=r"^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,4}$")]
    fe_frame_time_ms: BucketCounts
    fe_ws_decode_ms: BucketCounts
    fe_dropped_frames_total: _Count
    fe_gpu_memory_mb: Annotated[float, Field(ge=0, le=65536)] | None = None

    def bucket_lengths_ok(self) -> bool:
        return (
            len(self.fe_frame_time_ms.counts) == len(FE_FRAME_BUCKETS) + 1
            and len(self.fe_ws_decode_ms.counts) == len(FE_DECODE_BUCKETS) + 1
        )


class SessionRateLimiter:
    """Token bucket per session key, LRU-bounded so memory cannot grow."""

    def __init__(
        self,
        clock: Callable[[], float],
        *,
        interval_s: float = PUSH_INTERVAL_S,
        burst: int = BURST,
        max_sessions: int = MAX_TRACKED_SESSIONS,
    ) -> None:
        self._clock = clock
        self._rate = 1.0 / interval_s
        self._burst = float(burst)
        self._max = max_sessions
        self._buckets: OrderedDict[str, tuple[float, float]] = OrderedDict()

    def allow(self, key: str) -> bool:
        now = self._clock()
        tokens, last = self._buckets.pop(key, (self._burst, now))
        tokens = min(self._burst, tokens + (now - last) * self._rate)
        ok = tokens >= 1.0
        if ok:
            tokens -= 1.0
        self._buckets[key] = (tokens, now)
        while len(self._buckets) > self._max:
            self._buckets.popitem(last=False)
        return ok

    def __len__(self) -> int:
        return len(self._buckets)


class TelemetrySink:
    """Registers the `fe_*` and rejection series and folds payloads in."""

    def __init__(self, metrics: Metrics) -> None:
        r0 = register_r0(metrics)
        self.frame = r0["fe_frame_time_ms"]
        self.decode = r0["fe_ws_decode_ms"]
        self.dropped = r0["fe_dropped_frames_total"]
        self.gpu = r0["fe_gpu_memory_mb"]
        self.rejected: BoundedMetric = r0["telemetry_rejected_total"]
        for reason in REJECT_REASONS:
            self.rejected.labels(reason)

    def reject(self, reason: RejectReason) -> None:
        self.rejected.labels(reason).inc()

    def ingest(self, payload: FrontendTelemetry) -> None:
        _fold(
            self.frame,
            payload.screen,
            FE_FRAME_BUCKETS,
            payload.fe_frame_time_ms.counts,
        )
        _fold(
            self.decode,
            payload.screen,
            FE_DECODE_BUCKETS,
            payload.fe_ws_decode_ms.counts,
        )
        if payload.fe_dropped_frames_total:
            self.dropped.labels(payload.screen).inc(payload.fe_dropped_frames_total)
        if payload.fe_gpu_memory_mb is not None:
            self.gpu.labels(payload.screen).set(payload.fe_gpu_memory_mb)


def _fold(hist: BoundedMetric, screen: str, edges: tuple[float, ...], counts: list[int]) -> None:
    """Add pre-bucketed counts: each count is observed at its bucket's upper
    edge (the overflow slot just past the last edge), so server bucket counts
    equal client bucket counts. Bounded by `MAX_BUCKET_COUNT` per slot."""
    child = hist.labels(screen)
    for i, n in enumerate(counts):
        value = edges[i] if i < len(edges) else edges[-1] * 2
        for _ in range(n):
            child.observe(value)
