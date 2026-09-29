"""Domain errors for the audit module (M19)."""

from __future__ import annotations


class AuditError(Exception):
    """Base exception for the M19 `audit` module."""


class AuditChainBroken(AuditError):
    """Raised by `AuditVerifier` internals when a divergence is found and the
    caller asked for a raising API; the HTTP layer instead reports this as a
    `200` with `verified: false` (ticket AC "Tampering is detected and
    located") — this exception exists for callers that want fail-closed
    behaviour instead (e.g. the nightly job)."""

    def __init__(self, first_bad_id: int) -> None:
        super().__init__(f"audit chain diverges at id={first_bad_id}")
        self.first_bad_id = first_bad_id
