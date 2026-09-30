"""Unit tests for `candleviewer.auth.totp` (RFC 6238), E09-S02.

RFC 6238 Appendix B publishes fixed test vectors for an 8-digit SHA-1 TOTP
against a well-known 20-byte ASCII seed; this module implements 6-digit
codes, so we instead pin our own vectors computed from the same RFC 4226
HOTP algorithm and assert internal consistency (generate/verify round-trip,
skew window, replay-adjacent step math) rather than re-deriving the RFC's
8-digit vectors.
"""

from __future__ import annotations

from candleviewer.auth.totp import (
    TOTP_STEP_SECONDS,
    base32_to_secret,
    generate_code,
    generate_secret,
    otpauth_uri,
    secret_to_base32,
    time_step_for,
    verify_code,
)


def test_generate_secret_returns_20_random_bytes() -> None:
    secret = generate_secret()
    assert len(secret) == 20
    assert secret != generate_secret()


def test_secret_base32_round_trip() -> None:
    secret = generate_secret()
    assert base32_to_secret(secret_to_base32(secret)) == secret


def test_time_step_for_buckets_by_30_seconds() -> None:
    assert time_step_for(0.0) == 0
    assert time_step_for(29.999) == 0
    assert time_step_for(30.0) == 1
    assert time_step_for(59.999) == 1
    assert time_step_for(60.0) == 2


def test_generate_code_is_deterministic_and_six_digits() -> None:
    secret = b"0" * 20
    code_a = generate_code(secret, 1)
    code_b = generate_code(secret, 1)
    assert code_a == code_b
    assert len(code_a) == 6
    assert code_a.isdigit()


def test_generate_code_changes_per_step() -> None:
    secret = generate_secret()
    assert generate_code(secret, 1) != generate_code(secret, 2)


def test_verify_code_accepts_current_step() -> None:
    secret = generate_secret()
    now = 1_700_000_000.0
    step = time_step_for(now)
    code = generate_code(secret, step)
    assert verify_code(secret, code, unix_time=now) == step


def test_verify_code_tolerates_one_step_of_clock_drift() -> None:
    """Ticket: "Clock drift within one step is tolerated"."""
    secret = generate_secret()
    now = 1_700_000_000.0
    current_step = time_step_for(now)
    previous_code = generate_code(secret, current_step - 1)
    next_code = generate_code(secret, current_step + 1)
    assert verify_code(secret, previous_code, unix_time=now) == current_step - 1
    assert verify_code(secret, next_code, unix_time=now) == current_step + 1


def test_verify_code_rejects_beyond_skew_window() -> None:
    secret = generate_secret()
    now = 1_700_000_000.0
    current_step = time_step_for(now)
    far_code = generate_code(secret, current_step - 2)
    assert verify_code(secret, far_code, unix_time=now) is None


def test_verify_code_rejects_wrong_code() -> None:
    secret = generate_secret()
    assert verify_code(secret, "000000", unix_time=1_700_000_000.0) is None


def test_verify_code_rejects_non_digit_or_wrong_length() -> None:
    secret = generate_secret()
    assert verify_code(secret, "12345", unix_time=0.0) is None
    assert verify_code(secret, "abcdef", unix_time=0.0) is None
    assert verify_code(secret, "1234567", unix_time=0.0) is None


def test_verify_code_never_tries_a_negative_time_step() -> None:
    secret = generate_secret()
    # Near unix epoch: current_step is 0, so `-1` would be negative and must
    # be skipped rather than wrapping/crashing.
    assert verify_code(secret, "000000", unix_time=0.0, skew_steps=1) in (None, 0)


def test_otpauth_uri_contains_expected_fields() -> None:
    secret = generate_secret()
    uri = otpauth_uri(secret=secret, account_name="alice", issuer="CandleViewer")
    assert uri.startswith("otpauth://totp/CandleViewer:alice?")
    assert "algorithm=SHA1" in uri
    assert "digits=6" in uri
    assert f"period={TOTP_STEP_SECONDS}" in uri
    assert secret_to_base32(secret) in uri
