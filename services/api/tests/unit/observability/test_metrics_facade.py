"""Unit tests for the metrics facade (E04-T03)."""

from __future__ import annotations

import gc
import tracemalloc
from typing import Any

import pytest
import structlog
from prometheus_client import generate_latest
from prometheus_client.parser import text_string_to_metric_families

from candleviewer.observability.metrics import (
    DISALLOWED_LABEL_NAMES,
    NOOP_CHILD,
    Metrics,
    MetricsError,
    check_label_names,
)


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _families(m: Metrics) -> dict[str, Any]:
    text = generate_latest(m.registry).decode()
    return {f.name: f for f in text_string_to_metric_families(text)}


def test_metrics_env_label_is_injected_on_every_sample() -> None:
    m = Metrics("live")
    m.counter("x_total", "help", ("topic",)).labels("trades").inc()
    samples = [s for f in _families(m).values() for s in f.samples]
    assert samples and all(s.labels["env"] == "live" for s in samples)


def test_metrics_unknown_env_is_rejected() -> None:
    with pytest.raises(MetricsError):
        Metrics("prod")


def test_metrics_call_site_cannot_declare_env() -> None:
    with pytest.raises(MetricsError):
        Metrics("demo").counter("y_total", "help", ("env",))


@pytest.mark.parametrize("label", sorted(DISALLOWED_LABEL_NAMES))
def test_check_label_names_disallowed_label_fails(label: str) -> None:
    with pytest.raises(MetricsError):
        check_label_names("m", (label.upper(),))


def test_metrics_duplicate_registration_is_idempotent() -> None:
    m = Metrics("demo")
    a = m.gauge("g", "help", ("stage",))
    assert m.gauge("g", "help", ("stage",)) is a


def test_metrics_conflicting_registration_raises() -> None:
    m = Metrics("demo")
    m.gauge("g", "help", ("stage",))
    with pytest.raises(MetricsError):
        m.gauge("g", "help", ("topic",))


@pytest.mark.parametrize(
    "kwargs",
    [{"max_series": 0}, {"help_text": " "}],
)
def test_metrics_invalid_declaration_raises(kwargs: dict[str, Any]) -> None:
    args: dict[str, Any] = {"help_text": "h", "max_series": 5, **kwargs}
    with pytest.raises(MetricsError):
        Metrics("demo").counter("c_total", args["help_text"], max_series=args["max_series"])


def test_metrics_histogram_needs_buckets_and_enum_needs_states() -> None:
    m = Metrics("demo")
    with pytest.raises(MetricsError):
        m.histogram("h_seconds", "h", buckets=())
    with pytest.raises(MetricsError):
        m.enum("e_state", "h", states=())


def test_metrics_enum_and_histogram_export() -> None:
    m = Metrics("demo")
    m.enum("sock_state", "h", ("socket",), states=("up", "down")).labels("public").state("up")
    m.histogram("h_seconds", "h", buckets=(0.05, 0.1)).child().observe(0.07)
    fams = _families(m)
    assert "sock_state" in fams and "h_seconds" in fams


def test_cardinality_guard_caps_series_counts_breach_and_logs() -> None:
    m = Metrics("demo")
    metric = m.counter("burst_total", "h", ("symbol",), max_series=200)
    with structlog.testing.capture_logs() as logs:
        for i in range(250):
            metric.labels(f"S{i}").inc()
    assert metric.series_count == 200
    series = [s for s in _families(m)["burst"].samples if s.name == "burst_total"]
    assert len(series) == 200
    breach = _families(m)["metric_cardinality_breach"].samples
    assert any(s.labels.get("metric") == "burst_total" and s.value == 50 for s in breach)
    errors = [e for e in logs if e["event"] == "metric_cardinality_breach"]
    assert len(errors) == 1 and errors[0]["metric"] == "burst_total"
    assert m.check_cardinality() == ["burst_total"]


def test_cardinality_guard_existing_series_still_update_after_breach() -> None:
    m = Metrics("demo")
    metric = m.gauge("g", "h", ("k",), max_series=1)
    metric.labels("a").set(1)
    assert metric.labels("b") is NOOP_CHILD
    NOOP_CHILD.inc()
    NOOP_CHILD.dec()
    NOOP_CHILD.set(1)
    NOOP_CHILD.observe(1)
    NOOP_CHILD.state("x")
    metric.labels("a").set(7)
    assert m.snapshot(["g"]) == {"g{k=a}": 7.0}


def test_cardinality_guard_does_not_leak_memory() -> None:
    # Only allocations made by the facade/prometheus code count: unrelated allocations from other
    # threads, pytest or the allocator must not decide this test (#1871).
    only_facade = [
        tracemalloc.Filter(True, "*observability*metrics.py"),
        tracemalloc.Filter(True, "*prometheus_client*"),
    ]
    gc.collect()
    tracemalloc.start()  # before the metric exists, so its retained children are in the baseline
    try:
        m = Metrics("demo")
        metric = m.counter("leak_total", "h", ("k",), max_series=10)
        for i in range(10):
            metric.labels(str(i))
        for i in range(5_000):  # warm-up: absorbs one-off allocations (first-breach log, caches)
            metric.labels(f"warm{i}").inc()
        gc.collect()
        before = tracemalloc.take_snapshot().filter_traces(only_facade)
        # Guard against a glob that silently stops matching (growth would then read as 0).
        assert sum(st.size for st in before.statistics("filename")) > 0
        for i in range(20_000):
            metric.labels(f"new{i}").inc()
        gc.collect()
        after = tracemalloc.take_snapshot().filter_traces(only_facade)
    finally:
        tracemalloc.stop()
    grown = sum(s.size_diff for s in after.compare_to(before, "filename"))
    assert grown < 16_000  # O(1), not O(refused combinations)
    assert metric.series_count == 10
    assert metric.sample_count() == 10  # refused combinations are never retained


def test_staleness_gauge_grows_when_updates_stop() -> None:
    clock = FakeClock()
    m = Metrics("demo", clock=clock)
    st = m.staleness_gauge("topic_staleness_seconds", "h", ("topic",))
    st.touch("orderbook")
    clock.t += 3
    first = _families(m)["topic_staleness_seconds"].samples[0].value
    clock.t += 4
    second = _families(m)["topic_staleness_seconds"].samples[0].value
    assert (first, second) == (3.0, 7.0)
    st.touch("orderbook")
    assert st.age("orderbook") == 0.0


def test_staleness_gauge_untouched_key_is_infinite() -> None:
    st = Metrics("demo", clock=FakeClock()).staleness_gauge("s_seconds", "h", ("topic",))
    st.track("trades")
    st.track("trades")
    assert st.age("trades") == float("inf")


def test_metrics_registry_series_gauge_and_process_collectors() -> None:
    m = Metrics("demo", process_collectors=True)
    m.counter("a_total", "h", ("k",)).labels("x")
    fams = _families(m)
    assert fams["metrics_registry_series"].samples[0].value == 1.0
    assert "python_gc_objects_collected" in fams
    assert m.names() == ["a_total"] and m.get("a_total").name == "a_total"
