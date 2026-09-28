"""Real, host-wide listening-socket enumerator for the composition root.

`binding_check.enumerator_from_sockets` only sees the sockets `uvicorn`
itself created; it cannot see a Windows-side `portproxy` leak on WSL (the
exact hazard `20-architecture.md` "WSL hazards" names) because that traffic
never touches a Python-owned socket object. This module enumerates the
*process's actual open listening sockets* via `psutil` (which reads
`/proc/net/tcp*` on Linux/WSL and the OS socket table on Windows), which is
what `BindingSelfCheck` is designed to consult (module docstring: "enumerates
the process's real listening sockets rather than trusting the configured
bind string").

Fail-closed: `OSError`/`psutil.Error` propagate to the caller so
`BindingSelfCheck.run()` treats an unreadable socket table as unsafe, per its
own docstring.
"""

from __future__ import annotations

import psutil

from .binding_check import SocketAddressEnumerator


def enumerate_host_listening_sockets() -> list[str]:
    """Enumerate this process's real listening sockets via `psutil`.

    Returns `"host:port"` (or `"[host]:port"` for IPv6) strings for every
    connection in the `LISTEN` state owned by the current process. Any
    `psutil.Error` is re-raised as `OSError` so `BindingSelfCheck.run()`'s
    `except OSError` fail-closed path catches it uniformly regardless of
    platform.
    """
    try:
        process = psutil.Process()
        connections = process.net_connections(kind="inet")
    except psutil.Error as exc:  # pragma: no cover - platform/permission dependent
        raise OSError(str(exc)) from exc

    result: list[str] = []
    for conn in connections:
        if conn.status != psutil.CONN_LISTEN or conn.laddr is None:
            continue
        host, port = conn.laddr[:2]
        if ":" in host:
            result.append(f"[{host}]:{port}")
        else:
            result.append(f"{host}:{port}")
    return result


def real_socket_enumerator() -> SocketAddressEnumerator:
    """Return the enumerator the composition root wires into `BindingSelfCheck`."""
    return enumerate_host_listening_sockets
