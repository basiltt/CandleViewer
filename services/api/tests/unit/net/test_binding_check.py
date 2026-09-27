"""Unit tests for BindingSelfCheck (E09-T04)."""

from __future__ import annotations

from candleviewer.net.binding_check import BindingSelfCheck


def test_self_check_passes_when_bound_only_to_loopback() -> None:
    check = BindingSelfCheck(address_enumerator=lambda: ["127.0.0.1:8000"])
    result = check.run()
    assert result.safe is True
    assert result.reason_code == "net.binding_safe"


def test_self_check_passes_when_bound_to_a_mesh_address() -> None:
    check = BindingSelfCheck(address_enumerator=lambda: ["100.70.1.2:8000"])
    result = check.run()
    assert result.safe is True


def test_self_check_fails_on_ipv4_wildcard_bind() -> None:
    check = BindingSelfCheck(address_enumerator=lambda: ["0.0.0.0:8000"])
    result = check.run()
    assert result.safe is False
    assert result.reason_code == "net.public_binding_detected"


def test_self_check_fails_on_ipv6_wildcard_bind() -> None:
    check = BindingSelfCheck(address_enumerator=lambda: ["[::]:8000"])
    result = check.run()
    assert result.safe is False
    assert result.reason_code == "net.public_binding_detected"


def test_self_check_fails_closed_when_enumeration_raises() -> None:
    def _boom() -> list[str]:
        raise OSError("socket table unavailable")

    check = BindingSelfCheck(address_enumerator=_boom)
    result = check.run()
    assert result.safe is False
    assert result.reason_code == "net.binding_check_failed"


def test_self_check_reports_bound_addresses() -> None:
    check = BindingSelfCheck(address_enumerator=lambda: ["127.0.0.1:8000", "100.70.1.2:8001"])
    result = check.run()
    assert result.bound_addresses == ("127.0.0.1:8000", "100.70.1.2:8001")


def test_default_enumerator_raises_without_injection() -> None:
    # No enumerator injected -> the default raises OSError -> fail-closed.
    check = BindingSelfCheck()
    result = check.run()
    assert result.safe is False
    assert result.reason_code == "net.binding_check_failed"
