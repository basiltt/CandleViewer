"""Synthetic hot-loop harness for E04-K01.

Mirrors the ingestion pipeline shape from docs/plan/20-architecture.md §12.1:
parse -> transform -> emit, at a configurable message rate, with pluggable
instrumentation "configurations" (none / metrics / metrics+logs /
metrics+logs+tracing).

This module is intentionally dependency-light and synthetic: no network, no
real exchange payloads, no real secrets. Only the standard library, prometheus_client,
structlog, opentelemetry (api+sdk) and psutil are used, all already vendored for
services/api.
"""

from __future__ import annotations

import contextvars
import dataclasses
import gc
import statistics
import time
from collections.abc import Callable
from enum import Enum
from typing import Any

import psutil
import structlog
from prometheus_client import CollectorRegistry, Counter, Histogram

try:  # OpenTelemetry is optional at runtime; the harness degrades to a no-op tracer.
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        ConsoleSpanExporter,
        SimpleSpanProcessor,
    )
    from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

    _OTEL_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only when otel isn't installed
    _OTEL_AVAILABLE = False


class Configuration(str, Enum):
    """The four measured configurations from the ticket's Gherkin scenarios."""

    NONE = "none"
    METRICS_ONLY = "metrics_only"
    METRICS_STRUCTLOG = "metrics_structlog"
    METRICS_STRUCTLOG_OTEL = "metrics_structlog_otel"


class LabelShape(str, Enum):
    """Two label-handling shapes compared per the ticket's technical notes."""

    INLINE = "inline"  # label tuple computed inside the hot loop (naive)
    PRE_BOUND = "pre_bound"  # label lookup hoisted out of the loop (fast path)


_CANARY_SECRET = (
    "sk-canary-DO-NOT-USE-0000000000000000"  # obviously-fake, distinctive prefix
)


def _redaction_processor(
    logger: object, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Minimal structlog processor: strips known-sensitive keys.

    Mirrors the mandatory redaction processor described in ADR-0014 §4 well enough
    to measure its cost; the production processor lives with the real logging
    module once E04-T03 lands it.
    """

    sensitive_keys = ("api_key", "secret", "signature", "token", "password")
    for key in sensitive_keys:
        if key in event_dict:
            event_dict[key] = "***REDACTED***"
    return event_dict


@dataclasses.dataclass(frozen=True, slots=True)
class SyntheticMessage:
    """A synthetic market-data-shaped message (no real exchange payloads)."""

    topic: str
    symbol: str
    seq: int
    price: float
    qty: float
    api_key: str  # obviously-fake canary, only used to exercise redaction


_TOPICS = ("book.deep", "trades.public", "tickers")
_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def make_message(seq: int) -> SyntheticMessage:
    topic = _TOPICS[seq % len(_TOPICS)]
    symbol = _SYMBOLS[seq % len(_SYMBOLS)]
    return SyntheticMessage(
        topic=topic,
        symbol=symbol,
        seq=seq,
        price=100.0 + (seq % 1000) * 0.01,
        qty=1.0 + (seq % 7) * 0.1,
        api_key=_CANARY_SECRET,
    )


def parse(msg: SyntheticMessage) -> dict[str, Any]:
    """Stage 1: parse — synthetic decode into a plain dict."""

    return {
        "topic": msg.topic,
        "symbol": msg.symbol,
        "seq": msg.seq,
        "price": msg.price,
        "qty": msg.qty,
    }


def transform(parsed: dict[str, Any]) -> dict[str, Any]:
    """Stage 2: transform — cheap numeric derivation, mirrors bar/book update math."""

    parsed["notional"] = parsed["price"] * parsed["qty"]
    return parsed


def emit(transformed: dict[str, Any]) -> int:
    """Stage 3: emit — stand-in for WS fan-out; returns a checksum for validation."""

    return int(transformed["seq"])


@dataclasses.dataclass(slots=True)
class Instrumentation:
    """Bundles the per-message hooks for one configuration, built once per run."""

    on_message: Callable[[SyntheticMessage], None]
    logger: Any | None = None
    tracer: Any | None = None


def build_instrumentation(
    config: Configuration,
    label_shape: LabelShape,
    registry: CollectorRegistry,
    sampling_ratio: float = 1.0,
) -> Instrumentation:
    """Constructs the instrumentation hooks for one (configuration, label_shape) pair.

    Each hook does real work matching what production instrumentation would do,
    so the measured overhead is representative rather than a stub.
    """

    if config is Configuration.NONE:
        return Instrumentation(on_message=lambda msg: None)

    counter = Counter(
        "ws_messages_total",
        "Synthetic WS messages processed",
        ["topic", "symbol"],
        registry=registry,
    )
    histogram = Histogram(
        "topic_staleness_seconds",
        "Synthetic per-message processing latency",
        ["topic", "symbol"],
        registry=registry,
    )

    pre_bound_labels: dict[tuple[str, str], tuple[Any, Any]] = {}
    if label_shape is LabelShape.PRE_BOUND:
        for topic in _TOPICS:
            for symbol in _SYMBOLS:
                pre_bound_labels[(topic, symbol)] = (
                    counter.labels(topic=topic, symbol=symbol),
                    histogram.labels(topic=topic, symbol=symbol),
                )

    def metrics_hook(msg: SyntheticMessage, elapsed_s: float) -> None:
        if label_shape is LabelShape.PRE_BOUND:
            bound_counter, bound_hist = pre_bound_labels[(msg.topic, msg.symbol)]
            bound_counter.inc()
            bound_hist.observe(elapsed_s)
        else:
            counter.labels(topic=msg.topic, symbol=msg.symbol).inc()
            histogram.labels(topic=msg.topic, symbol=msg.symbol).observe(elapsed_s)

    if config is Configuration.METRICS_ONLY:

        def on_message(msg: SyntheticMessage) -> None:
            start = time.perf_counter()
            metrics_hook(msg, time.perf_counter() - start)

        return Instrumentation(on_message=on_message)

    log_sink_path = "NUL" if _is_windows() else "/dev/null"
    log_sink = open(log_sink_path, "w", encoding="utf-8")  # noqa: SIM115
    structlog.configure(
        processors=[
            _redaction_processor,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(file=log_sink),
        cache_logger_on_first_use=True,
    )
    logger = structlog.get_logger("obs_baseline_overhead")

    if config is Configuration.METRICS_STRUCTLOG:

        def on_message(msg: SyntheticMessage) -> None:
            start = time.perf_counter()
            metrics_hook(msg, time.perf_counter() - start)
            logger.info(
                "message_processed",
                topic=msg.topic,
                symbol=msg.symbol,
                seq=msg.seq,
                api_key=msg.api_key,
            )

        return Instrumentation(on_message=on_message, logger=logger)

    # METRICS_STRUCTLOG_OTEL
    tracer = _build_tracer(sampling_ratio)

    def on_message(msg: SyntheticMessage) -> None:
        start = time.perf_counter()
        with tracer.start_as_current_span("ingest.message") as span:
            span.set_attribute("topic", msg.topic)
            span.set_attribute("symbol", msg.symbol)
            metrics_hook(msg, time.perf_counter() - start)
            logger.info(
                "message_processed",
                topic=msg.topic,
                symbol=msg.symbol,
                seq=msg.seq,
                api_key=msg.api_key,
            )

    return Instrumentation(on_message=on_message, logger=logger, tracer=tracer)


def _is_windows() -> bool:
    import platform

    return platform.system() == "Windows"


def _build_tracer(sampling_ratio: float) -> Any:
    if not _OTEL_AVAILABLE:
        return _NoOpTracer()
    provider = TracerProvider(
        resource=Resource.create({"service.name": "obs-baseline-overhead-harness"}),
        sampler=TraceIdRatioBased(sampling_ratio),
    )
    devnull_path = "NUL" if _is_windows() else "/dev/null"
    devnull = open(devnull_path, "w", encoding="utf-8")  # noqa: SIM115
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter(out=devnull)))
    return provider.get_tracer("obs_baseline_overhead")


class _NoOpTracer:
    """Fallback tracer used only if opentelemetry isn't installed in this env."""

    class _NoOpSpan:
        def set_attribute(self, *_args: Any, **_kwargs: Any) -> None:
            return None

        def __enter__(self) -> _NoOpTracer._NoOpSpan:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    def start_as_current_span(self, _name: str) -> _NoOpTracer._NoOpSpan:
        return self._NoOpSpan()


@dataclasses.dataclass(frozen=True, slots=True)
class RunResult:
    """One repeat's measured result for one configuration."""

    configuration: str
    label_shape: str
    message_count: int
    duration_s: float
    cpu_percent: float
    rss_bytes: int
    p50_latency_ns: float
    p95_latency_ns: float
    p99_latency_ns: float


def run_pipeline(
    config: Configuration,
    label_shape: LabelShape,
    *,
    rate_per_s: int,
    duration_s: float,
    latency_sample_every: int = 50,
) -> RunResult:
    """Runs the parse->transform->emit pipeline at a fixed message rate for
    duration_s seconds, returning CPU/RSS/latency measurements.

    Rate control batches messages against a wall-clock schedule rather than
    busy-polling per message: polling every message at high rates would itself
    dominate the CPU%-delta signal we're trying to measure. Every ~5ms we compute
    how many messages *should* have been emitted by now (given rate_per_s) and
    process exactly that many, then sleep briefly. This keeps the harness's own
    scheduling overhead roughly constant across configurations and out of the
    per-configuration comparison (the ticket's contextvars/asyncio.create_task
    cost is measured separately in measure_contextvars_cost).
    """

    registry = CollectorRegistry()
    instrumentation = build_instrumentation(config, label_shape, registry)

    process = psutil.Process()
    gc.collect()
    cpu_times_start = process.cpu_times()
    wall_start = time.perf_counter()
    end_at = wall_start + duration_s

    latencies_ns: list[float] = []
    message_count = 0
    poll_interval_s = 0.005

    while True:
        now = time.perf_counter()
        if now >= end_at:
            break
        target_count = int((now - wall_start) * rate_per_s)
        while message_count < target_count:
            msg = make_message(message_count)

            sample_latency = message_count % latency_sample_every == 0
            t0 = time.perf_counter_ns() if sample_latency else 0

            parsed = parse(msg)
            transformed = transform(parsed)
            emit(transformed)
            instrumentation.on_message(msg)

            if sample_latency:
                latencies_ns.append(time.perf_counter_ns() - t0)

            message_count += 1
        time.sleep(poll_interval_s)

    cpu_times_end = process.cpu_times()
    wall_elapsed = time.perf_counter() - wall_start
    rss_bytes = process.memory_info().rss
    cpu_seconds = (cpu_times_end.user + cpu_times_end.system) - (
        cpu_times_start.user + cpu_times_start.system
    )
    cpu_percent = (cpu_seconds / wall_elapsed * 100.0) if wall_elapsed > 0 else 0.0

    latencies_ns.sort()
    p50, p95, p99 = _percentiles(latencies_ns, (0.50, 0.95, 0.99))

    return RunResult(
        configuration=config.value,
        label_shape=label_shape.value,
        message_count=message_count,
        duration_s=wall_elapsed,
        cpu_percent=cpu_percent,
        rss_bytes=rss_bytes,
        p50_latency_ns=p50,
        p95_latency_ns=p95,
        p99_latency_ns=p99,
    )


def _percentiles(
    sorted_values: list[float], quantiles: tuple[float, ...]
) -> tuple[float, ...]:
    if not sorted_values:
        return tuple(0.0 for _ in quantiles)
    results = []
    for q in quantiles:
        idx = min(int(len(sorted_values) * q), len(sorted_values) - 1)
        results.append(sorted_values[idx])
    return tuple(results)


_context_var: contextvars.ContextVar[int] = contextvars.ContextVar(
    "obs_baseline_ctxvar"
)


def measure_contextvars_cost(iterations: int) -> float:
    """Measures the per-call cost of setting a contextvar (proxy for the
    propagation overhead asyncio.create_task incurs by copying the context).

    Returns mean nanoseconds per set() call.
    """

    start = time.perf_counter_ns()
    for i in range(iterations):
        _context_var.set(i)
    elapsed = time.perf_counter_ns() - start
    return elapsed / iterations if iterations else 0.0


def summarize_repeats(results: list[RunResult]) -> dict[str, float]:
    """Aggregates repeats of the same configuration into mean/stdev per metric."""

    cpu = [r.cpu_percent for r in results]
    rss = [r.rss_bytes for r in results]
    p95 = [r.p95_latency_ns for r in results]
    return {
        "cpu_percent_mean": statistics.mean(cpu),
        "cpu_percent_stdev": statistics.stdev(cpu) if len(cpu) > 1 else 0.0,
        "rss_bytes_mean": statistics.mean(rss),
        "rss_bytes_stdev": statistics.stdev(rss) if len(rss) > 1 else 0.0,
        "p95_latency_ns_mean": statistics.mean(p95),
        "p95_latency_ns_stdev": statistics.stdev(p95) if len(p95) > 1 else 0.0,
    }
