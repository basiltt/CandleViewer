"""SR-092: an encrypted backup is useless without the (distinct) backup key (E07-X02).

Uses a throwaway key generated in-test; fixtures only, no production data.
"""

from __future__ import annotations

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def test_sr092_backup_without_key_or_with_runtime_kek_fails_to_decrypt() -> None:
    backup_key, runtime_kek = AESGCM.generate_key(256), AESGCM.generate_key(256)
    assert backup_key != runtime_kek
    nonce = b"\x00" * 12
    blob = AESGCM(backup_key).encrypt(nonce, b"fixture-parquet-bytes", b"cv-backup")
    assert b"fixture-parquet-bytes" not in blob
    with pytest.raises(InvalidTag):
        AESGCM(runtime_kek).decrypt(nonce, blob, b"cv-backup")
    assert AESGCM(backup_key).decrypt(nonce, blob, b"cv-backup") == b"fixture-parquet-bytes"
