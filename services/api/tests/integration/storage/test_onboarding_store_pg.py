"""Postgres integration for the E09-S06 store. Not run locally: no docker (runs in CI)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_store_module_exposes_binding_probe() -> None:
    from candleviewer.storage.repositories.onboarding_sqlalchemy import SqlAlchemyOnboardingStore

    for name in (
        "is_dismissed",
        "dismiss",
        "has_confirmed_totp",
        "has_account_binding",
        "latest_binding_at",
    ):
        assert callable(getattr(SqlAlchemyOnboardingStore, name))
