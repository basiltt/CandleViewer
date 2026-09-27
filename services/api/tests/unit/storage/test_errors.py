"""Unit tests for `candleviewer.storage.errors` (E07-T01).

Error-code stability: a frozen mapping of exception class -> string code, so
log/`system_events` consumers do not break silently on a rename (ticket
"Test plan").
"""

from __future__ import annotations

from candleviewer.storage.errors import (
    ERROR_CODES,
    StorageDiskCritical,
    StorageError,
    StorageExportVerifyFailed,
    StorageRetentionBlockedByPin,
    StorageSchemaDrift,
    StorageTierUnavailable,
)


def test_error_codes_are_stable_and_unique() -> None:
    assert ERROR_CODES == {
        StorageError: "STORAGE_ERROR",
        StorageTierUnavailable: "STORAGE_TIER_UNAVAILABLE",
        StorageExportVerifyFailed: "STORAGE_EXPORT_VERIFY_FAILED",
        StorageSchemaDrift: "STORAGE_SCHEMA_DRIFT",
        StorageRetentionBlockedByPin: "STORAGE_RETENTION_BLOCKED_BY_PIN",
        StorageDiskCritical: "STORAGE_DISK_CRITICAL",
    }
    assert len(set(ERROR_CODES.values())) == len(ERROR_CODES)


def test_every_storage_error_is_an_exception_subclass() -> None:
    for cls in ERROR_CODES:
        assert issubclass(cls, Exception)


def test_storage_tier_unavailable_carries_its_class_code() -> None:
    err = StorageTierUnavailable("questdb down")
    assert err.code == "STORAGE_TIER_UNAVAILABLE"
    assert str(err) == "questdb down"
