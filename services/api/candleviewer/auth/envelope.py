"""Envelope encryption for the TOTP seed (E09-S02 "Secret handling").

Mirrors `auth/hashing.py`'s boundary note: `candleviewer.auth` (M18) is not
on the `secrets` (M2) allow-list (`module-contracts.toml` M18 `allowed`
does not include `candleviewer.secrets`; ADR-0009's KEK lives behind M2).
This module therefore never imports `candleviewer.secrets` and never reads
a KEK from anywhere itself — it accepts an already-resolved 256-bit key as
a plain `bytes` argument (`TotpEncryptor(key=...)`), exactly like `Hasher`
accepts an already-resolved pepper string. The composition root
(`candleviewer.app`, mirroring how it will eventually wire a real M2
`SecretsService`) is responsible for supplying that key; until that wiring
exists, callers pass a process-local, non-persisted key (see
`app.py`'s `AuthService` construction) — acceptable only because the
schema documents `secret_enc` as "plaintext only in services/api/secrets/"
and this ticket's own scope is M18, not M2's KEK custody (ADR-0009 owns
that; this ticket implements the *shape* the column requires).

Algorithm: AES-256-GCM (`cryptography` — already a transitive dependency
via other pinned packages; a direct pin is added in `pyproject.toml` in
this PR). Ciphertext layout stored in `mfa_methods.secret_enc` is
`nonce(12) || ciphertext || tag(16)`; `secret_key_ref` records which KEK
version produced it (`"local-dev-v1"` for the process-local placeholder).
"""

from __future__ import annotations

import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

#: Matches `mfa_methods.secret_key_ref` for the process-local placeholder
#: key described in the module docstring above.
LOCAL_KEY_REF = "local-dev-v1"

_NONCE_LEN = 12


class TotpEncryptor:
    """AES-256-GCM encrypt/decrypt for one TOTP seed at a time."""

    def __init__(self, key: bytes, *, key_ref: str = LOCAL_KEY_REF) -> None:
        if len(key) != 32:
            raise ValueError("TotpEncryptor key must be 32 bytes (AES-256)")
        self._aead = AESGCM(key)
        self.key_ref = key_ref

    def encrypt(self, plaintext_secret: bytes) -> bytes:
        nonce = os.urandom(_NONCE_LEN)
        ciphertext = self._aead.encrypt(nonce, plaintext_secret, associated_data=None)
        return nonce + ciphertext

    def decrypt(self, secret_enc: bytes) -> bytes:
        nonce, ciphertext = secret_enc[:_NONCE_LEN], secret_enc[_NONCE_LEN:]
        return self._aead.decrypt(nonce, ciphertext, associated_data=None)
