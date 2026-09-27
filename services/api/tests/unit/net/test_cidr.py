"""Unit tests for CidrAllowList (E09-T04)."""

from __future__ import annotations

from candleviewer.net.cidr import CidrAllowList


def test_allow_list_accepts_address_inside_configured_cidr() -> None:
    allow = CidrAllowList(["100.64.0.0/10"])
    assert allow.is_allowed("100.70.1.2") is True


def test_allow_list_rejects_address_outside_configured_cidr() -> None:
    allow = CidrAllowList(["100.64.0.0/10"])
    assert allow.is_allowed("8.8.8.8") is False


def test_allow_list_always_accepts_ipv4_loopback() -> None:
    allow = CidrAllowList([])
    assert allow.is_allowed("127.0.0.1") is True


def test_allow_list_always_accepts_ipv6_loopback() -> None:
    allow = CidrAllowList([])
    assert allow.is_allowed("::1") is True


def test_allow_list_matches_boundary_addresses_of_a_cidr() -> None:
    allow = CidrAllowList(["100.64.0.0/24"])
    assert allow.is_allowed("100.64.0.0") is True
    assert allow.is_allowed("100.64.0.255") is True
    assert allow.is_allowed("100.64.1.0") is False


def test_allow_list_supports_ipv6_cidrs() -> None:
    allow = CidrAllowList(["fd7a:115c:a1e0::/48"])
    assert allow.is_allowed("fd7a:115c:a1e0::1") is True
    assert allow.is_allowed("fd00:dead:beef::1") is False


def test_allow_list_unwraps_ipv4_mapped_ipv6_addresses() -> None:
    # A dual-stack listener must not let an IPv4-mapped address evade an
    # IPv4-only allow list.
    allow = CidrAllowList(["100.64.0.0/10"])
    assert allow.is_allowed("::ffff:100.70.1.2") is True
    assert allow.is_allowed("::ffff:8.8.8.8") is False


def test_allow_list_rejects_unparseable_address_fail_closed() -> None:
    allow = CidrAllowList(["100.64.0.0/10"])
    assert allow.is_allowed("not-an-ip") is False


def test_allow_list_rejects_empty_string_fail_closed() -> None:
    allow = CidrAllowList(["100.64.0.0/10"])
    assert allow.is_allowed("") is False
