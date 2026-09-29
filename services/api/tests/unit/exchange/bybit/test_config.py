"""Config validator tests: allowlisted hosts only, `recv_window_ms` bound."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from candleviewer.exchange.bybit.config import RestClientConfig


def test_allowlisted_host_accepted() -> None:
    cfg = RestClientConfig(base_url="https://api-demo.bybit.com")
    assert cfg.base_url == "https://api-demo.bybit.com"


@pytest.mark.parametrize(
    "base_url",
    [
        "https://evil.example.com",
        "http://api.bybit.com",
        "https://api.bybit.com/v5",
        "https://api.bybit.com?x=1",
    ],
)
def test_disallowed_or_malformed_base_url_rejected(base_url: str) -> None:
    with pytest.raises(ValidationError):
        RestClientConfig(base_url=base_url)


@pytest.mark.parametrize("recv_window_ms", [0, -1, 10_001])
def test_recv_window_out_of_bounds_rejected(recv_window_ms: int) -> None:
    with pytest.raises(ValidationError):
        RestClientConfig(base_url="https://api.bybit.com", recv_window_ms=recv_window_ms)


def test_default_recv_window_is_5000() -> None:
    cfg = RestClientConfig(base_url="https://api.bybit.com")
    assert cfg.recv_window_ms == 5000
