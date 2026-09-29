"""Tests for `candleviewer.observability.secret_type.Secret` (SR-007)."""

from __future__ import annotations

from candleviewer.observability.secret_type import Secret


def test_str_never_prints_the_wrapped_value() -> None:
    s = Secret("CANARY-SECRET")
    assert "CANARY-SECRET" not in str(s)
    assert str(s) == "[redacted]"


def test_repr_never_prints_the_wrapped_value() -> None:
    s = Secret("CANARY-SECRET")
    assert "CANARY-SECRET" not in repr(s)


def test_format_never_prints_the_wrapped_value() -> None:
    s = Secret("CANARY-SECRET")
    assert "CANARY-SECRET" not in f"{s}"
    assert "CANARY-SECRET" not in format(s, "")


def test_fstring_interpolation_never_leaks_the_value() -> None:
    s = Secret("CANARY-SECRET")
    message = f"key is {s}"
    assert "CANARY-SECRET" not in message


def test_reveal_returns_the_original_value() -> None:
    s = Secret("CANARY-SECRET")
    assert s.reveal() == "CANARY-SECRET"


def test_equality_compares_wrapped_values() -> None:
    assert Secret("a") == Secret("a")
    assert Secret("a") != Secret("b")
