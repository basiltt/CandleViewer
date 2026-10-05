"""E08-T05: the exchange_smoke demo-only guard fails closed (negative tests).

Runs in the default lane (it is NOT under tests/exchange_smoke/, dials nothing).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from tests.exchange_smoke._guard import SmokeGuardError, assert_demo_only, opted_in

_API = Path(__file__).resolve().parents[3]
_REPO = _API.parents[1]


@pytest.mark.parametrize(
    "env",
    [
        {"CV_ENVIRONMENT": "live"},
        {"CV_SMOKE_ENV": "mainnet"},
        {"CV_BYBIT_REST_BASE_URL": "https://api.bybit.com"},
        {"CV_BYBIT_WS_URL": "wss://stream.bybit.com/v5/private?env=live"},
        {"CV_BYBIT_API_KEY": "DUMMYKEY_not_a_real_key"},
    ],
)
def test_smoke_guard_live_configuration_fails_fast_with_explicit_error(
    env: dict[str, str],
) -> None:
    with pytest.raises(SmokeGuardError, match=r"demo-only|no credentials"):
        assert_demo_only({"CV_EXCHANGE_SMOKE": "1", **env})


def test_smoke_guard_demo_configuration_passes() -> None:
    assert_demo_only(
        {
            "CV_EXCHANGE_SMOKE": "1",
            "CV_ENVIRONMENT": "demo",
            "CV_BYBIT_REST_BASE_URL": "https://api-demo.bybit.com/",
        }
    )


def test_smoke_suite_is_opt_in() -> None:
    assert not opted_in({})
    assert not opted_in({"CV_EXCHANGE_SMOKE": "true"})
    assert opted_in({"CV_EXCHANGE_SMOKE": "1"})


def test_default_ci_job_deselects_exchange_smoke() -> None:
    lane = (_REPO / ".github" / "workflows" / "_job-py.yml").read_text(encoding="utf-8")
    assert '-m "not exchange_smoke' in lane
    markers = tomllib.loads((_API / "pyproject.toml").read_text(encoding="utf-8"))
    assert any(
        m.startswith("exchange_smoke:") for m in markers["tool"]["pytest"]["ini_options"]["markers"]
    )


def test_every_smoke_test_carries_the_marker() -> None:
    src = (_API / "tests" / "exchange_smoke" / "test_demo_smoke.py").read_text(encoding="utf-8")
    assert "pytestmark = pytest.mark.exchange_smoke" in src
