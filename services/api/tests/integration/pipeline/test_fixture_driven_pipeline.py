"""Fixture-driven pipeline integration test (E03-T06 acceptance criterion
"Integration suite runs fully offline").

Loads the manifest-verified recorded fixture through the ingestion layer's
normalised-event parser and asserts it produces the expected typed domain
events — the smallest real slice of "recorded WS session -> normalised
events" available while book/bars/orderflow/gateway are still R0 scaffolds
(each pipeline stage's own ticket extends this suite with its own golden
comparison as it lands real logic, per the ticket's "Out of scope": this
Task only provides the harness, not product-level golden fixtures for
features that do not exist yet).

Runs with outbound network denied except loopback (`tests/_ci_network_guard.py`,
autouse via conftest) — CONSTITUTION C-13.5/ADR-0012.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from candleviewer.exchange.base import Ticker, Trade
from candleviewer.ingestion.synthetic_feed import SyntheticFeedError, load_sample_records

_REPO_ROOT = Path(__file__).resolve().parents[5]
_MANIFEST = _REPO_ROOT / "tests" / "fixtures" / "MANIFEST.sha256"
_VERIFY_SCRIPT = _REPO_ROOT / "tools" / "ci" / "verify_fixture_manifest.py"
_FIXTURE = _REPO_ROOT / "packages" / "fixtures" / "raw" / "synthetic_sample.jsonl"


def test_fixture_manifest_verifies_clean() -> None:
    """Scenario: a missing/corrupt fixture would fail loudly (CI-INT-001/002)
    rather than silently skip — exercised directly here so the integration
    job fails fast, before the pipeline suite below even runs, on a bad
    fixture."""
    result = subprocess.run(  # noqa: S603 — fixed argv, no shell, trusted script under test
        [
            sys.executable,
            str(_VERIFY_SCRIPT),
            "--manifest",
            str(_MANIFEST),
            "--repo-root",
            str(_REPO_ROOT),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_recorded_fixture_replays_into_normalised_events() -> None:
    """The manifest-verified recorded fixture parses into a non-empty,
    correctly-typed sequence of normalised domain events — the pipeline's
    first stage (ingestion -> normalised events)."""
    records = load_sample_records(_FIXTURE)

    assert len(records) > 0
    assert all(isinstance(r, Trade | Ticker) for r in records)
    trades = [r for r in records if isinstance(r, Trade)]
    tickers = [r for r in records if isinstance(r, Ticker)]
    assert len(trades) > 0
    assert len(tickers) > 0
    for trade in trades:
        assert trade.symbol
        assert trade.price > 0
        assert trade.size > 0


def test_malformed_fixture_fails_loudly_not_silently(tmp_path: Path) -> None:
    """A malformed fixture record raises a typed error rather than being
    silently dropped or skipped — the same "fail loudly" principle the
    manifest check applies at the file level, applied here at the record
    level."""
    bad_fixture = tmp_path / "bad.jsonl"
    bad_fixture.write_text('{"kind": "trade", "data": {}}\n', encoding="utf-8")

    with pytest.raises(SyntheticFeedError):
        load_sample_records(bad_fixture)
