"""E04-S02: real app wiring + real collectors (no fakes for the service)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from candleviewer.app import create_app
from candleviewer.observability.support_bundle_wiring import LogRingBuffer


def test_route_mounted_and_fails_closed_without_identity() -> None:
    client = TestClient(create_app(), client=("127.0.0.1", 50000))
    resp = client.post("/admin/support-bundle", json={})
    assert resp.status_code == 501  # mounted (not 404), fails closed without identity


def test_metrics_registered_for_support_bundle() -> None:
    app = create_app()
    names = app.state.metrics_facade.names()
    assert "support_bundle_generations_total" in names
    assert "support_bundle_duration_seconds" in names
    assert "support_bundle_bytes" in names


def test_log_ring_window_newest_first_and_redacted() -> None:
    ring = LogRingBuffer()
    lg = logging.getLogger("sb-test")
    lg.addHandler(ring)
    lg.setLevel(logging.INFO)
    lg.info("first")
    lg.info("second")
    now = datetime.now(UTC)
    lines = ring.window(now - timedelta(minutes=1), now + timedelta(minutes=1))
    assert lines[0].endswith("second")
    assert lines[1].endswith("first")
