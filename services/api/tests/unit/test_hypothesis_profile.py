"""The CI Hypothesis profile must not use wall-clock deadlines (#1855)."""

from __future__ import annotations

import os

from hypothesis import settings

from tests._hypothesis_profiles import CI, DEV


def test_active_profile_in_ci_has_no_deadline() -> None:
    if os.environ.get("HYPOTHESIS_PROFILE") != CI:
        return  # only meaningful when CI selects the profile
    active = settings()
    assert active.deadline is None
    assert active.derandomize is True
    assert active.database is None


def test_registered_profiles_have_expected_shape() -> None:
    ci = settings.get_profile(CI)
    dev = settings.get_profile(DEV)
    assert ci.deadline is None and ci.derandomize and ci.print_blob
    assert dev.deadline is not None and dev.deadline.total_seconds() >= 2
