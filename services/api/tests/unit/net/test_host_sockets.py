"""Real listening-socket enumerator (E09-T04): the boot/hourly self-check's
actual `psutil`-backed address source, as opposed to the fake enumerators
used elsewhere in the `net` test suite.
"""

from __future__ import annotations

from types import SimpleNamespace

import psutil
import pytest

from candleviewer.net.host_sockets import (
    enumerate_host_listening_sockets,
    real_socket_enumerator,
)


def _conn(status: str, host: str, port: int) -> SimpleNamespace:
    return SimpleNamespace(status=status, laddr=(host, port))


def test_enumerate_filters_to_listen_state_only(monkeypatch: pytest.MonkeyPatch) -> None:
    conns = [
        _conn(psutil.CONN_LISTEN, "127.0.0.1", 8000),
        _conn(psutil.CONN_ESTABLISHED, "127.0.0.1", 9000),
    ]
    monkeypatch.setattr(
        psutil,
        "Process",
        lambda: SimpleNamespace(net_connections=lambda kind: conns),
    )

    result = enumerate_host_listening_sockets()

    assert result == ["127.0.0.1:8000"]


def test_enumerate_formats_ipv6_addresses_with_brackets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conns = [_conn(psutil.CONN_LISTEN, "::1", 8000)]
    monkeypatch.setattr(
        psutil,
        "Process",
        lambda: SimpleNamespace(net_connections=lambda kind: conns),
    )

    result = enumerate_host_listening_sockets()

    assert result == ["[::1]:8000"]


def test_enumerate_skips_connections_with_no_local_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conns = [SimpleNamespace(status=psutil.CONN_LISTEN, laddr=None)]
    monkeypatch.setattr(
        psutil,
        "Process",
        lambda: SimpleNamespace(net_connections=lambda kind: conns),
    )

    assert enumerate_host_listening_sockets() == []


def test_enumerate_wraps_psutil_error_as_oserror_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise() -> SimpleNamespace:
        raise psutil.AccessDenied()

    monkeypatch.setattr(psutil, "Process", _raise)

    with pytest.raises(OSError):
        enumerate_host_listening_sockets()


def test_real_socket_enumerator_returns_a_callable() -> None:
    enumerator = real_socket_enumerator()
    assert callable(enumerator)
