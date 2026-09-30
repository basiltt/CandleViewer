"""Unit tests for `candleviewer.auth.recovery_codes`, E09-S02."""

from __future__ import annotations

import re

from candleviewer.auth.recovery_codes import (
    RECOVERY_CODE_COUNT,
    generate_recovery_code,
    generate_recovery_codes,
    hash_recovery_code,
    normalize_recovery_code,
)

_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
_CODE_RE = re.compile(rf"^[{_ALPHABET}]{{4}}-[{_ALPHABET}]{{4}}-[{_ALPHABET}]{{4}}$")


def test_generate_recovery_code_matches_grouped_unambiguous_shape() -> None:
    code = generate_recovery_code()
    assert _CODE_RE.match(code)
    for banned in "0O1L":
        assert banned not in code


def test_generate_recovery_codes_returns_ten_unique_codes_by_default() -> None:
    codes = generate_recovery_codes()
    assert len(codes) == RECOVERY_CODE_COUNT == 10
    assert len(set(codes)) == len(codes)


def test_generate_recovery_codes_respects_count() -> None:
    assert len(generate_recovery_codes(count=3)) == 3


def test_normalize_recovery_code_is_case_and_separator_insensitive() -> None:
    assert normalize_recovery_code("7F2A-91BC-4DE0") == "7F2A91BC4DE0"
    assert normalize_recovery_code("7f2a 91bc 4de0") == "7F2A91BC4DE0"
    assert normalize_recovery_code(" 7f2a91bc4de0 ") == "7F2A91BC4DE0"


def test_hash_recovery_code_is_stable_across_equivalent_input_forms() -> None:
    assert hash_recovery_code("7F2A-91BC-4DE0") == hash_recovery_code("7f2a91bc4de0")


def test_hash_recovery_code_is_sha256_hex() -> None:
    digest = hash_recovery_code("7F2A-91BC-4DE0")
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


def test_hash_recovery_code_differs_for_different_codes() -> None:
    assert hash_recovery_code("7F2A-91BC-4DE0") != hash_recovery_code("2222-2222-2222")
