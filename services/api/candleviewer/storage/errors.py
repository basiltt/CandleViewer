"""Domain errors for the storage module (M10).

Each exception carries a stable `code` string attribute (frozen mapping
tested by `services/api/tests/unit/storage/test_errors.py`) so log consumers
and `system_events` rows never break silently on a refactor that renames a
class (ticket "Scope / Deliverables": "each with a stable string code used in
logs and `system_events`").
"""

from __future__ import annotations


class StorageError(Exception):
    """Base exception for the M10 `storage` module."""

    code: str = "STORAGE_ERROR"


class StorageTierUnavailable(StorageError):
    """A tier client failed to connect or answer at boot or at call time.

    Raised by `health()` implementations' internal probes and by repository
    methods when their tier is down; the supervisor treats this as
    readiness-blocking for `postgres`, degraded-but-serving for `questdb`
    reads-from-cold, and export-blocking only for `cold` (ticket "Technical
    notes / design").
    """

    code = "STORAGE_TIER_UNAVAILABLE"


class StorageExportVerifyFailed(StorageError):
    """`ColdTierRepository.verify_checksums` found a mismatch after export."""

    code = "STORAGE_EXPORT_VERIFY_FAILED"


class StorageSchemaDrift(StorageError):
    """A tier's on-disk/on-wire schema no longer matches this package's models."""

    code = "STORAGE_SCHEMA_DRIFT"


class StorageRetentionBlockedByPin(StorageError):
    """`RetentionRepository.apply` refused to roll off or delete a pinned range."""

    code = "STORAGE_RETENTION_BLOCKED_BY_PIN"


class StorageRetentionBlockedUnverified(StorageError):
    """A hot partition may not be dropped: its cold export is missing or unverified (Sec.5.3)."""

    code = "STORAGE_RETENTION_BLOCKED_UNVERIFIED"


class StorageRetentionBlockedByReplay(StorageError):
    """A partition is referenced by an active `replay_sessions` row."""

    code = "STORAGE_RETENTION_BLOCKED_REPLAY"


class StorageDiskCritical(StorageError):
    """Free disk fell below the configured critical threshold for a tier."""

    code = "STORAGE_DISK_CRITICAL"


#: Frozen mapping from exception class to its stable code, asserted by a
#: unit test so a future rename cannot silently change a log/system_events
#: value (ticket "Scope / Deliverables").
ERROR_CODES: dict[type[StorageError], str] = {
    StorageError: StorageError.code,
    StorageTierUnavailable: StorageTierUnavailable.code,
    StorageExportVerifyFailed: StorageExportVerifyFailed.code,
    StorageSchemaDrift: StorageSchemaDrift.code,
    StorageRetentionBlockedByPin: StorageRetentionBlockedByPin.code,
    StorageRetentionBlockedUnverified: StorageRetentionBlockedUnverified.code,
    StorageRetentionBlockedByReplay: StorageRetentionBlockedByReplay.code,
    StorageDiskCritical: StorageDiskCritical.code,
}
