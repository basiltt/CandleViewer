"""Boot + hourly self-check: are we actually bound to loopback/mesh only?

Enumerates the process's real listening sockets rather than trusting the
configured bind string, because the leak mode this guards against
(`20-architecture.md` "WSL hazards": a `0.0.0.0` binding leak via Windows
`portproxy`) is precisely a mismatch between configuration and reality.

Fail-closed: if the socket table cannot be read, the result is unsafe.
"""

from __future__ import annotations

import socket
from collections.abc import Callable, Iterable
from dataclasses import dataclass

PUBLIC_WILDCARDS = frozenset({"0.0.0.0", "::"})  # noqa: S104 - detection constants, not a bind call

SocketAddressEnumerator = Callable[[], Iterable[str]]


@dataclass(frozen=True)
class BindingCheckResult:
    """Outcome of one self-check pass."""

    safe: bool
    bound_addresses: tuple[str, ...]
    reason_code: str
    reason_text: str


class BindingSelfCheck:
    """Enumerates bound listening addresses for the current process.

    `address_enumerator` is injected (defaults to a psutil-free stdlib
    fallback) so tests can simulate arbitrary socket tables without binding
    real sockets, and so the WSL portproxy cross-check (best-effort, only
    when the helper is available) can be swapped in without touching the
    core logic.
    """

    def __init__(
        self,
        address_enumerator: SocketAddressEnumerator | None = None,
    ) -> None:
        self._enumerate = address_enumerator or _enumerate_own_listening_sockets

    def run(self) -> BindingCheckResult:
        try:
            addresses = tuple(self._enumerate())
        except OSError:
            return BindingCheckResult(
                safe=False,
                bound_addresses=(),
                reason_code="net.binding_check_failed",
                reason_text=(
                    "Could not enumerate listening sockets; treating the binding as "
                    "unsafe (fail-closed)."
                ),
            )

        public = [addr for addr in addresses if _host_of(addr) in PUBLIC_WILDCARDS]
        if public:
            return BindingCheckResult(
                safe=False,
                bound_addresses=addresses,
                reason_code="net.public_binding_detected",
                reason_text=(
                    f"Public wildcard binding detected on {', '.join(public)}; the "
                    "trading terminal must never be reachable from the public "
                    "internet. Starting in read-only mode."
                ),
            )
        return BindingCheckResult(
            safe=True,
            bound_addresses=addresses,
            reason_code="net.binding_safe",
            reason_text="All listening sockets are loopback/mesh-only.",
        )


def _host_of(address: str) -> str:
    # address is "host:port" or "[::]:port"; split on the last colon so
    # IPv6 addresses (which contain colons) are handled correctly.
    if address.startswith("["):
        return address[1 : address.index("]")]
    return address.rsplit(":", 1)[0]


def _enumerate_own_listening_sockets() -> list[str]:
    """Best-effort stdlib enumeration of this process's listening sockets.

    A full cross-platform socket-table walk (netstat/`/proc/net`, and on
    WSL the Windows-side `portproxy` table via the helper named in the
    ticket) is environment-specific and is wired in the composition root
    (E02-T05) where the actual server sockets are created and can be
    inspected directly; this default only guards against import-time
    misuse and is always overridden with a real enumerator in production
    wiring.
    """
    raise OSError("no server sockets registered; inject an address_enumerator")


def enumerator_from_sockets(sockets: list[socket.socket]) -> SocketAddressEnumerator:
    """Build an enumerator from live server sockets (used by the composition root)."""

    def _enumerate() -> list[str]:
        result = []
        for sock in sockets:
            host, port = sock.getsockname()[:2]
            if ":" in host:
                result.append(f"[{host}]:{port}")
            else:
                result.append(f"{host}:{port}")
        return result

    return _enumerate
