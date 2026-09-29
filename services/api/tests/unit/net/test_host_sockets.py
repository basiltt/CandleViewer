"""Real listening-socket enumerator (E09-T04): the boot/hourly self-check's
actual `psutil`-backed address source, as opposed to the fake enumerators
used elsewhere in the `net` test suite.
"""

from __future__ import annotations

from types import SimpleNamespace

import psutil
import pytest

from candleviewer.net import host_sockets
from candleviewer.net.host_sockets import (
    enumerate_host_listening_sockets,
    real_socket_enumerator,
)


def _conn(status: str, host: str, port: int) -> SimpleNamespace:
    return SimpleNamespace(status=status, laddr=(host, port))


def _no_portproxy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable the Windows portproxy probe so tests are platform-independent."""
    monkeypatch.setattr(host_sockets, "_enumerate_windows_portproxy_sockets", lambda: [])


def test_enumerate_filters_to_listen_state_only(monkeypatch: pytest.MonkeyPatch) -> None:
    conns = [
        _conn(psutil.CONN_LISTEN, "127.0.0.1", 8000),
        _conn(psutil.CONN_ESTABLISHED, "127.0.0.1", 9000),
    ]
    monkeypatch.setattr(psutil, "net_connections", lambda kind: conns)
    _no_portproxy(monkeypatch)

    result = enumerate_host_listening_sockets()

    assert result == ["127.0.0.1:8000"]


def test_enumerate_formats_ipv6_addresses_with_brackets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conns = [_conn(psutil.CONN_LISTEN, "::1", 8000)]
    monkeypatch.setattr(psutil, "net_connections", lambda kind: conns)
    _no_portproxy(monkeypatch)

    result = enumerate_host_listening_sockets()

    assert result == ["[::1]:8000"]


def test_enumerate_skips_connections_with_no_local_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conns = [
        SimpleNamespace(status=psutil.CONN_LISTEN, laddr=None),
        _conn(psutil.CONN_LISTEN, "127.0.0.1", 8000),
    ]
    monkeypatch.setattr(psutil, "net_connections", lambda kind: conns)
    _no_portproxy(monkeypatch)

    assert enumerate_host_listening_sockets() == ["127.0.0.1:8000"]


def test_enumerate_wraps_psutil_error_as_oserror_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(kind: str) -> list[SimpleNamespace]:
        raise psutil.AccessDenied()

    monkeypatch.setattr(psutil, "net_connections", _raise)
    _no_portproxy(monkeypatch)

    with pytest.raises(OSError):
        enumerate_host_listening_sockets()


def test_enumerate_raises_oserror_when_result_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty enumeration is a broken check, not an empty host, so it must
    fail closed rather than let `BindingSelfCheck` report a vacuous pass."""
    monkeypatch.setattr(psutil, "net_connections", lambda kind: [])
    _no_portproxy(monkeypatch)

    with pytest.raises(OSError):
        enumerate_host_listening_sockets()


def test_enumerate_includes_portproxy_listeners_owned_by_another_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Windows `portproxy` rule forwards traffic to WSL without the WSL
    process (or this process) owning a matching socket object; the check
    must still see it via the portproxy table."""
    monkeypatch.setattr(psutil, "net_connections", lambda kind: [])
    monkeypatch.setattr(
        host_sockets,
        "_enumerate_windows_portproxy_sockets",
        lambda: ["0.0.0.0:8443"],
    )

    result = enumerate_host_listening_sockets()

    assert result == ["0.0.0.0:8443"]


def test_real_socket_enumerator_returns_a_callable() -> None:
    enumerator = real_socket_enumerator()
    assert callable(enumerator)
