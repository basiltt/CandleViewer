"""Pytest network guard (E03-T03).

ADR-0012 ("offline deterministic CI, no live venue in CI") and SR-140
("CI must not hold production Bybit credentials") require that no test in
this suite can reach the live exchange or any other non-loopback host. This
module wraps `socket.socket.connect`/`connect_ex` so that any attempted
connection to a host outside the allow-list raises immediately, before the
underlying OS call is made — so a test cannot "succeed" by timing out
against a firewalled host and swallowing the error.

Allow-list: loopback (`127.0.0.1`, `::1`) plus any hostname/IP listed in the
`CV_CI_ALLOWED_HOSTS` environment variable (comma-separated), which CI sets
to the service-container hostnames for the `integration_db` subset
(SR-131). Locally (no env var set) only loopback is allowed.

This module contains no test collection itself; it is imported by
`tests/conftest.py` via an autouse, session-scoped fixture so every test
in `services/api/tests/**` is covered without per-file boilerplate.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from collections.abc import Iterator
from typing import Any

import pytest

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


class NetworkGuardViolation(RuntimeError):
    """Raised when a test attempts an outbound connection to a denied host."""


def _allowed_hosts() -> frozenset[str]:
    extra = os.environ.get("CV_CI_ALLOWED_HOSTS", "")
    hosts = {h.strip() for h in extra.split(",") if h.strip()}
    return frozenset(_LOOPBACK_HOSTS | hosts)


def _is_loopback_address(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def is_host_allowed(host: str, *, allowed_hosts: frozenset[str] | None = None) -> bool:
    """Return True iff `host` may be connected to from inside the test suite."""
    allowed = allowed_hosts if allowed_hosts is not None else _allowed_hosts()
    if host in allowed:
        return True
    return _is_loopback_address(host)


_Address = tuple[Any, ...] | str | bytes


def _extract_host(address: _Address) -> str | None:
    # `connect`/`connect_ex` accept a family-dependent tuple; IPv4/IPv6 both
    # have the host as element 0. Unix-domain sockets pass a str/bytes path,
    # not a host — always allowed (no network egress involved).
    if isinstance(address, tuple) and address:
        return str(address[0])
    return None


def _violation(host: str) -> NetworkGuardViolation:
    return NetworkGuardViolation(
        f"outbound network denied in CI: connection to {host!r} is not in "
        "the loopback/CV_CI_ALLOWED_HOSTS allow-list (ADR-0012, SR-140)"
    )


@pytest.fixture(autouse=True, scope="session")
def _cv_network_guard() -> Iterator[None]:
    """Autouse session fixture: deny non-loopback outbound connections.

    Patches `socket.socket.connect` and `socket.socket.connect_ex` for the
    lifetime of the test session. Guard is process-global by design (a
    background thread opening a socket must be caught too), so it is not
    reset per-test.
    """
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def _guarded_connect(self: socket.socket, address: _Address) -> None:
        host = _extract_host(address)
        if host is not None and not is_host_allowed(host):
            raise _violation(host)
        real_connect(self, address)

    def _guarded_connect_ex(self: socket.socket, address: _Address) -> int:
        host = _extract_host(address)
        if host is not None and not is_host_allowed(host):
            raise _violation(host)
        return real_connect_ex(self, address)

    socket.socket.connect = _guarded_connect  # type: ignore[method-assign,assignment]
    socket.socket.connect_ex = _guarded_connect_ex  # type: ignore[method-assign,assignment]
    try:
        yield
    finally:
        socket.socket.connect = real_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = real_connect_ex  # type: ignore[method-assign]
