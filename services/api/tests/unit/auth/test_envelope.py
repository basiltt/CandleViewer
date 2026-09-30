"""Unit tests for `candleviewer.auth.envelope.TotpEncryptor`, E09-S02."""

from __future__ import annotations

import os

import pytest

from candleviewer.auth.envelope import LOCAL_KEY_REF, TotpEncryptor


def test_encrypt_decrypt_round_trip() -> None:
    key = os.urandom(32)
    encryptor = TotpEncryptor(key)
    seed = os.urandom(20)
    ciphertext = encryptor.encrypt(seed)
    assert encryptor.decrypt(ciphertext) == seed


def test_encrypt_output_is_not_plaintext_and_includes_nonce_and_tag() -> None:
    key = os.urandom(32)
    encryptor = TotpEncryptor(key)
    seed = b"0" * 20
    ciphertext = encryptor.encrypt(seed)
    assert seed not in ciphertext
    # nonce(12) + ciphertext(len(seed)) + tag(16)
    assert len(ciphertext) == 12 + len(seed) + 16


def test_encrypt_is_nondeterministic_due_to_random_nonce() -> None:
    key = os.urandom(32)
    encryptor = TotpEncryptor(key)
    seed = os.urandom(20)
    assert encryptor.encrypt(seed) != encryptor.encrypt(seed)


def test_decrypt_rejects_tampered_ciphertext() -> None:
    key = os.urandom(32)
    encryptor = TotpEncryptor(key)
    ciphertext = bytearray(encryptor.encrypt(os.urandom(20)))
    ciphertext[-1] ^= 0xFF
    with pytest.raises(Exception):  # noqa: B017 - cryptography raises InvalidTag
        encryptor.decrypt(bytes(ciphertext))


def test_decrypt_rejects_wrong_key() -> None:
    seed = os.urandom(20)
    ciphertext = TotpEncryptor(os.urandom(32)).encrypt(seed)
    other = TotpEncryptor(os.urandom(32))
    with pytest.raises(Exception):  # noqa: B017 - cryptography raises InvalidTag
        other.decrypt(ciphertext)


def test_key_ref_defaults_to_local_placeholder() -> None:
    encryptor = TotpEncryptor(os.urandom(32))
    assert encryptor.key_ref == LOCAL_KEY_REF


def test_key_ref_can_be_overridden() -> None:
    encryptor = TotpEncryptor(os.urandom(32), key_ref="kek-v2")
    assert encryptor.key_ref == "kek-v2"


def test_rejects_non_32_byte_key() -> None:
    with pytest.raises(ValueError):
        TotpEncryptor(os.urandom(16))
