"""E04-T06: stage arithmetic, clock-offset correction, sampling, attribution."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.observability.latency import (
    STAGE_BUCKETS,
    EndToEndSampler,
    Stage,
    StageRecorder,
    StageStamps,
    dominant_stage,
    e2e_seconds,
    record_stages,
    stage_durations,
)
from candleviewer.observability.metrics import Metrics

BASE = 1_700_000_000_000


def _stamps(skew_ms: int = 0) -> StageStamps:
    # True exchange event 10 ms before receipt; exchange clock ahead by skew.
    return StageStamps(
        t_exchange=BASE - 10 + skew_ms,
        t_received=BASE,
        t_parsed=BASE + 2,
        t_derived=BASE + 9,
        t_emitted=BASE + 15,
    )


def test_stage_durations_subtract_each_stage() -> None:
    d = stage_durations(_stamps(), clock_offset_ms=0)
    assert d == {"exchange": 0.01, "parse": 0.002, "derive": 0.007, "fanout": 0.006}


def test_stage_durations_exchange_clock_800ms_ahead_is_offset_corrected() -> None:
    d = stage_durations(_stamps(skew_ms=800), clock_offset_ms=800)
    assert d["exchange"] == pytest.approx(0.01)


def test_stage_durations_no_offset_reports_exchange_unavailable() -> None:
    d = stage_durations(_stamps(skew_ms=800), clock_offset_ms=None)
    assert d["exchange"] is None
    assert d["parse"] == 0.002


def test_stage_durations_negative_duration_is_unavailable_not_negative() -> None:
    s = StageStamps(BASE, BASE, BASE - 1, BASE, BASE)
    assert stage_durations(s, 0)["parse"] is None
    # Uncorrected skew larger than the true latency must not go negative.
    assert stage_durations(_stamps(skew_ms=800), clock_offset_ms=0)["exchange"] is None


@given(lat=st.integers(0, 5000), skew=st.integers(-5000, 5000))
def test_stage_durations_corrected_exchange_stage_is_independent_of_skew(
    lat: int, skew: int
) -> None:
    s = StageStamps(BASE - lat + skew, BASE, BASE, BASE, BASE)
    assert stage_durations(s, skew)["exchange"] == pytest.approx(lat / 1000)


def test_stages_sum_to_backend_envelope() -> None:
    d = stage_durations(_stamps(), 0)
    backend = sum(v for k, v in d.items() if k != "exchange" and v is not None)
    s = _stamps()
    assert backend == pytest.approx((s.t_emitted - s.t_received) / 1000)


def test_record_stages_observes_available_stages_only() -> None:
    m = Metrics("demo")
    h = m.histogram("ingest_stage_seconds", "h", ("stage",), buckets=STAGE_BUCKETS, max_series=4)
    record_stages(h, _stamps(), None)
    snap = m.snapshot(["ingest_stage_seconds"])
    assert h.series_count == 3
    assert snap


def test_sampler_selects_exactly_one_in_n() -> None:
    s = EndToEndSampler(100)
    assert sum(s.should_sample() for _ in range(1000)) == 10


def test_sampler_rejects_zero() -> None:
    with pytest.raises(ValueError):
        EndToEndSampler(0)


def test_e2e_seconds_paired_and_guarded() -> None:
    assert e2e_seconds(BASE, BASE + 42) == 0.042
    assert e2e_seconds(BASE, BASE - 1) is None


def test_dominant_stage_names_slow_fanout() -> None:
    means: dict[Stage, float | None] = {
        "exchange": None,
        "parse": 0.002,
        "derive": 0.008,
        "fanout": 0.240,
    }
    assert dominant_stage(means) == "fanout"


def test_dominant_stage_none_when_no_data() -> None:
    assert dominant_stage({"parse": None}) is None
    assert dominant_stage({"parse": 0.0}) is None


def test_stage_recorder_records_only_sampled_events() -> None:
    m = Metrics("demo")
    h = m.histogram("ingest_stage_seconds", "h", ("stage",), buckets=STAGE_BUCKETS, max_series=4)
    rec = StageRecorder(h, 10)
    sampled = sum(rec.on_event(_stamps(), None) for _ in range(100))
    assert sampled == 10
    v = m.registry.get_sample_value("ingest_stage_seconds_count", {"env": "demo", "stage": "parse"})
    assert v == 10
    ex = m.registry.get_sample_value(
        "ingest_stage_seconds_count", {"env": "demo", "stage": "exchange"}
    )
    assert ex == 0
