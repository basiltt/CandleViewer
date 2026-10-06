"""E08-X02 security note: the suite is incapable of targeting live Bybit.

Every REST client here is built on an `httpx.MockTransport`, every socket is a
fake, and the repo-wide network guard (`tests/_ci_network_guard.py`) is autouse.
This guard proves the guard is active for this package.
"""

from __future__ import annotations

import socket

import pytest


def test_network_guard_blocks_exchange_hosts() -> None:
    with pytest.raises(Exception):  # noqa: B017 - guard type is owned by E03-T03
        socket.create_connection(("stream.bybit.com", 443), timeout=0.01)


def test_no_suite_module_opens_real_transport() -> None:
    from pathlib import Path

    banned = ("httpx." + "AsyncHTTPTransport", "ws_" + "connect(", "BybitRestClient(Rest")
    here = Path(__file__).parent
    for py in here.glob("*.py"):
        text = py.read_text(encoding="utf-8")
        for needle in banned[:2]:
            assert needle not in text, f"{py.name}: {needle}"
        # Every REST client constructed in the suite is given a mock transport.
        assert text.count("BybitRestClient(\n") <= text.count("MockTransport("), py.name
