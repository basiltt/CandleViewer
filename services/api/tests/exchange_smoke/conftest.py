"""`exchange_smoke` suite wiring (E08-T05). See `tests/exchange_smoke/README.md`.

Opt-in: without `CV_EXCHANGE_SMOKE=1` every test here is skipped, and the
default CI py lane also deselects the marker (`-m "not exchange_smoke"`).
When opted in, the demo-only guard runs **before any test** and aborts the
whole session on a live-looking configuration (fail closed). Only then are the
resolved IPs of the two demo hosts added to the network guard's allow-list
(`tests/_ci_network_guard.py` reads `CV_CI_ALLOWED_HOSTS` per connect).
"""

from __future__ import annotations

import os
import socket
from collections.abc import Iterator

import pytest

from tests.exchange_smoke._guard import DEMO_HOSTS, assert_demo_only, opted_in


@pytest.fixture(autouse=True, scope="session")
def _demo_only_session() -> Iterator[None]:
    env = dict(os.environ)
    if not opted_in(env):
        pytest.skip("exchange_smoke is opt-in: set CV_EXCHANGE_SMOKE=1 (demo only)")
    assert_demo_only(env)  # raises SmokeGuardError -> every test errors, nothing dials
    ips = {info[4][0] for h in DEMO_HOSTS for info in socket.getaddrinfo(h, 443)}
    previous = os.environ.get("CV_CI_ALLOWED_HOSTS", "")
    hosts = {str(ip) for ip in ips} | ({previous} - {""})
    os.environ["CV_CI_ALLOWED_HOSTS"] = ",".join(sorted(hosts))
    try:
        yield
    finally:
        os.environ["CV_CI_ALLOWED_HOSTS"] = previous
