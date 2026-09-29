"""Unit tests for `benchmarks.questdb_hot_tier.runner`'s skip-when-
unconfigured path. No network, no sleeps, no live QuestDB — this only
exercises the env-var guard.
"""

from __future__ import annotations

import pytest

from benchmarks.questdb_hot_tier.runner import NotConfigured, _require_env


def test_require_env_raises_not_configured_when_both_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CV_QUESTDB_PG_DSN", raising=False)
    monkeypatch.delenv("CV_QUESTDB_ILP_HOST", raising=False)

    with pytest.raises(NotConfigured):
        _require_env()


def test_require_env_raises_not_configured_when_dsn_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CV_QUESTDB_PG_DSN", raising=False)
    monkeypatch.setenv("CV_QUESTDB_ILP_HOST", "localhost:9009")

    with pytest.raises(NotConfigured):
        _require_env()


def test_require_env_raises_not_configured_when_ilp_host_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CV_QUESTDB_PG_DSN", "postgresql://u:p@localhost:8812/qdb")
    monkeypatch.delenv("CV_QUESTDB_ILP_HOST", raising=False)

    with pytest.raises(NotConfigured):
        _require_env()


def test_require_env_returns_both_values_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CV_QUESTDB_PG_DSN", "postgresql://u:p@localhost:8812/qdb")
    monkeypatch.setenv("CV_QUESTDB_ILP_HOST", "localhost:9009")

    dsn, ilp_host = _require_env()

    assert dsn == "postgresql://u:p@localhost:8812/qdb"
    assert ilp_host == "localhost:9009"
