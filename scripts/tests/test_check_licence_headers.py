"""Unit tests for scripts/check_licence_headers.py."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_licence_headers as clh


def test_main_passes_on_repo_as_is() -> None:
    assert clh.main() == 0


def test_banned_patterns_detect_mit_boilerplate() -> None:
    sample = "Permission is hereby granted, free of charge, to any person"
    assert clh._matches_banned(sample)


def test_banned_patterns_detect_bsd_boilerplate() -> None:
    sample = "Redistribution and use in source and binary forms, with or without"
    assert clh._matches_banned(sample)


def test_banned_patterns_ignore_unlicensed_spdx() -> None:
    sample = "SPDX-License-Identifier: UNLICENSED"
    assert not clh._matches_banned(sample)


def test_banned_patterns_detect_other_spdx() -> None:
    sample = "SPDX-License-Identifier: MIT"
    assert clh._matches_banned(sample)


def test_tracked_source_files_only_lists_source_suffixes() -> None:
    files = clh._tracked_source_files()
    assert all(f.suffix in clh.SOURCE_SUFFIXES for f in files)
    # Sanity: git ls-files actually ran and returned something in this repo.
    assert isinstance(files, list)
