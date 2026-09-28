"""Smoke test for the E04-K01 harness: asserts a broken run isn't mistaken for a
fast one, per the ticket's "Test plan" section.
"""

from __future__ import annotations

from tests.perf.obs_baseline_overhead.harness import (
    Configuration,
    LabelShape,
    measure_contextvars_cost,
    run_pipeline,
)


def test_run_pipeline_none_config_produces_expected_message_count() -> None:
    result = run_pipeline(
        Configuration.NONE,
        LabelShape.INLINE,
        rate_per_s=200,
        duration_s=0.5,
    )
    # At 200 msg/s for 0.5s we expect roughly 100 messages; allow generous
    # scheduling slack (this is a smoke test, not a perf assertion).
    assert 50 <= result.message_count <= 400
    assert result.cpu_percent >= 0.0
    assert result.rss_bytes > 0


def test_run_pipeline_all_configurations_produce_messages() -> None:
    for config in Configuration:
        result = run_pipeline(
            config,
            LabelShape.PRE_BOUND,
            rate_per_s=200,
            duration_s=0.3,
        )
        assert result.message_count > 0, f"{config} produced zero messages"


def test_redaction_processor_masks_canary_secret() -> None:
    from tests.perf.obs_baseline_overhead.harness import _redaction_processor

    event = {"api_key": "sk-canary-DO-NOT-USE-0000000000000000", "other": "ok"}
    redacted = _redaction_processor(None, "info", dict(event))
    assert redacted["api_key"] == "***REDACTED***"
    assert redacted["other"] == "ok"


def test_measure_contextvars_cost_returns_positive_ns() -> None:
    per_call_ns = measure_contextvars_cost(1000)
    assert per_call_ns > 0.0
