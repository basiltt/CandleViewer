"""Unit tests for `candleviewer.storage.health` (E07-T01)."""

from __future__ import annotations

from candleviewer.storage.health import StorageHealthReport, TierHealth, TierState


def test_overall_ok_true_only_when_every_tier_ok() -> None:
    report = StorageHealthReport(
        tiers=(
            TierHealth(tier="postgres", state=TierState.OK),
            TierHealth(tier="questdb", state=TierState.DEGRADED),
        )
    )
    assert report.overall_ok() is False


def test_tier_lookup_by_name() -> None:
    report = StorageHealthReport(
        tiers=(TierHealth(tier="postgres", state=TierState.OK, detail="fine"),)
    )
    found = report.tier("postgres")
    assert found is not None
    assert found.detail == "fine"
    assert report.tier("cold") is None
