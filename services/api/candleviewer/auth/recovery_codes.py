"""Single-use recovery codes: generation, hashing, formatting (E09-S02).

Ticket "Technical notes": "Codes are generated from secrets.token_bytes
with an unambiguous alphabet (no 0/O/1/l) and are grouped for readability."
Hashing is plain SHA-256 (`recovery_codes.code_hash sha256_hex`, ticket
"stored only as sha256_hex") — not Argon2id: these are high-entropy,
machine-generated random codes (not user-chosen passwords), so a fast hash
plus the database's uniqueness/lookup index is the right trade-off, exactly
like `mfa_challenges.nonce` elsewhere in this schema.
"""

from __future__ import annotations

import hashlib
import secrets

#: Ticket: "no 0/O/1/l" (unambiguous when read aloud or handwritten).
_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"

#: Ticket "Scope / Deliverables": "10 single-use codes generated at enrolment".
RECOVERY_CODE_COUNT = 10

#: Ticket "recovery code use ... forces re-enrolment ... when fewer than
#: three codes remain" (`22-api-openapi.yaml` /auth/mfa/recovery description).
LOW_CODE_THRESHOLD = 3

_GROUP_LEN = 4
_GROUPS = 3  # 12 alphabet characters total, grouped 4-4-4 -> "XXXX-XXXX-XXXX"


def generate_recovery_code() -> str:
    """One human-typeable, grouped recovery code, e.g. `7F2A-91BC-4DE0`."""
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(_GROUP_LEN * _GROUPS))
    return "-".join(raw[i : i + _GROUP_LEN] for i in range(0, len(raw), _GROUP_LEN))


def generate_recovery_codes(count: int = RECOVERY_CODE_COUNT) -> list[str]:
    return [generate_recovery_code() for _ in range(count)]


def normalize_recovery_code(code: str) -> str:
    """Case/whitespace/dash-insensitive canonical form used for hashing and
    comparison, so a user typing `7f2a91bc4de0` matches the stored
    `7F2A-91BC-4DE0`."""
    return code.strip().upper().replace("-", "").replace(" ", "")


def hash_recovery_code(code: str) -> str:
    """`sha256_hex` of the normalized code — matches the `recovery_codes
    .code_hash` column's `sha256_hex` domain (`0001_identity_rbac_sessions_
    mfa.py`)."""
    normalized = normalize_recovery_code(code)
    return hashlib.sha256(normalized.encode("ascii")).hexdigest()
