"""Unit tests for tools/ci/release_semver.py (E03-T11, CI-REL-002)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.changelog_lib import Bump
from tools.ci.release_semver import Version, compute_next_version


def test_version_parse_accepts_v_prefix() -> None:
    assert Version.parse("v1.2.3") == Version(1, 2, 3)


def test_version_parse_rejects_invalid() -> None:
    import pytest

    with pytest.raises(ValueError):
        Version.parse("not-a-version")


def test_patch_bump_pre_1_0() -> None:
    result = compute_next_version(Version(0, 3, 1), Bump.PATCH)
    assert result.ok
    assert result.next_version == Version(0, 3, 2)


def test_minor_bump_pre_1_0() -> None:
    result = compute_next_version(Version(0, 3, 1), Bump.MINOR)
    assert result.ok
    assert result.next_version == Version(0, 4, 0)


def test_major_bump_pre_1_0_without_allow_flag_fails_ci_rel_002() -> None:
    result = compute_next_version(Version(0, 9, 4), Bump.MAJOR)
    assert not result.ok
    assert result.error_code == "CI-REL-002"
    assert "1.0.0 requires explicit" in result.reason


def test_major_bump_pre_1_0_with_allow_flag_produces_1_0_0() -> None:
    result = compute_next_version(Version(0, 9, 4), Bump.MAJOR, allow_1_0_0=True)
    assert result.ok
    assert result.next_version == Version(1, 0, 0)


def test_major_bump_post_1_0_does_not_need_the_guard() -> None:
    result = compute_next_version(Version(1, 4, 2), Bump.MAJOR)
    assert result.ok
    assert result.next_version == Version(2, 0, 0)


def test_no_bump_returns_current_version_unchanged() -> None:
    result = compute_next_version(Version(0, 3, 1), Bump.NONE)
    assert result.ok
    assert result.next_version == Version(0, 3, 1)
