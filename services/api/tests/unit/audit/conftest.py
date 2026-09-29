"""Fixtures for the audit unit tests (fakes live in `audit_fakes`)."""

from __future__ import annotations

import pytest
from audit_fakes import FakeAuditRepository, FakeClock


@pytest.fixture
def repo() -> FakeAuditRepository:
    return FakeAuditRepository()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()
