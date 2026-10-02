"""Fixtures for cv-storage-open-unrooted (E07-X02, SR-097)."""


def bad(user_value):
    return open(user_value, "rb")  # ruleid: cv-storage-open-unrooted


def good(paths):
    return open(paths.partition_dir / "f.parquet", "rb")  # ok: cv-storage-open-unrooted
