"""CIDR allow-list matcher for the mesh-only guard.

Pure, in-memory, no I/O. Budget: <50 us p99 per request (C-14.2-style budget
noted in the ticket's Performance notes), no per-request allocation beyond
constructing the `ipaddress` object for the candidate address.
"""

from __future__ import annotations

from ipaddress import (
    IPv4Address,
    IPv6Address,
    ip_address,
    ip_network,
)


class CidrAllowList:
    """Fail-closed prefix match against a fixed set of allowed networks.

    Loopback (127.0.0.0/8, ::1/128) is always allowed in addition to the
    configured networks, since local health checks and same-host tooling
    must keep working. IPv4-mapped IPv6 addresses (`::ffff:a.b.c.d`) are
    unwrapped to their IPv4 form before matching so a dual-stack listener
    cannot be used to evade an IPv4-only allow list.
    """

    __slots__ = ("_networks",)

    def __init__(self, cidrs: list[str]) -> None:
        networks = [ip_network(c, strict=False) for c in cidrs]
        networks.append(ip_network("127.0.0.0/8"))
        networks.append(ip_network("::1/128"))
        self._networks = tuple(networks)

    def is_allowed(self, source_address: str) -> bool:
        """Return True only if `source_address` is inside an allowed network.

        Any parse failure is treated as unsafe (fail-closed) — malformed or
        unrecognised addresses are never permitted through.
        """
        try:
            addr = ip_address(source_address)
        except ValueError:
            return False

        if isinstance(addr, IPv6Address) and addr.ipv4_mapped is not None:
            addr = addr.ipv4_mapped

        for network in self._networks:
            if isinstance(addr, IPv4Address) and network.version == 4:
                if addr in network:
                    return True
            elif isinstance(addr, IPv6Address) and network.version == 6:
                if addr in network:
                    return True
        return False
