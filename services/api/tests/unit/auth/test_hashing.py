"""Unit tests for `candleviewer.auth.hashing.Hasher` (E09-S01)."""

from __future__ import annotations

from candleviewer.auth.hashing import DEFAULT_ARGON2_PARAMS, Hasher, constant_time_eq


def test_hasher_hash_then_verify_roundtrips() -> None:
    hasher = Hasher(pepper="pepper-value")
    digest = hasher.hash("correct-horse-battery-staple")
    assert hasher.verify(digest, "correct-horse-battery-staple") is True


def test_hasher_verify_wrong_password_returns_false() -> None:
    hasher = Hasher(pepper="pepper-value")
    digest = hasher.hash("correct-horse-battery-staple")
    assert hasher.verify(digest, "wrong-password") is False


def test_hasher_verify_dummy_always_false() -> None:
    hasher = Hasher(pepper="pepper-value")
    assert hasher.verify_dummy("any-password-at-all") is False


def test_hasher_different_pepper_fails_verification() -> None:
    hasher_a = Hasher(pepper="pepper-a")
    hasher_b = Hasher(pepper="pepper-b")
    digest = hasher_a.hash("correct-horse-battery-staple")
    assert hasher_b.verify(digest, "correct-horse-battery-staple") is False


def test_hasher_needs_rehash_false_for_current_params() -> None:
    hasher = Hasher()
    digest = hasher.hash("correct-horse-battery-staple", DEFAULT_ARGON2_PARAMS)
    assert hasher.needs_rehash(digest, DEFAULT_ARGON2_PARAMS) is False


def test_hasher_needs_rehash_true_for_stale_params() -> None:
    hasher = Hasher()
    stale_params = {"m": 8, "t": 1, "p": 1}
    digest = hasher.hash("correct-horse-battery-staple", stale_params)
    assert hasher.needs_rehash(digest, DEFAULT_ARGON2_PARAMS) is True


def test_constant_time_eq_true_and_false() -> None:
    assert constant_time_eq("abc", "abc") is True
    assert constant_time_eq("abc", "abd") is False
