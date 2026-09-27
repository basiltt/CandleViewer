"""Protocol-conformance tests (E07-T01 "Test plan").

`typing.runtime_checkable` + a structural `isinstance` assertion per
implementation, proving every fake actually satisfies its Protocol without
inheriting from it.
"""

from __future__ import annotations

from candleviewer.storage.repositories import (
    ColdTierRepository,
    MarketDataRepository,
    RelationalRepository,
    RetentionRepository,
    UnitOfWork,
)
from candleviewer.storage.testing import (
    FakeColdTierRepository,
    FakeMarketDataRepository,
    FakeRelationalRepository,
    FakeRetentionRepository,
    FakeUnitOfWork,
)


def test_fake_market_data_repository_satisfies_protocol() -> None:
    assert isinstance(FakeMarketDataRepository(), MarketDataRepository)


def test_fake_relational_repository_satisfies_protocol() -> None:
    assert isinstance(FakeRelationalRepository(), RelationalRepository)


def test_fake_unit_of_work_satisfies_protocol() -> None:
    assert isinstance(FakeUnitOfWork(), UnitOfWork)


def test_fake_cold_tier_repository_satisfies_protocol() -> None:
    assert isinstance(FakeColdTierRepository(), ColdTierRepository)


def test_fake_retention_repository_satisfies_protocol() -> None:
    assert isinstance(FakeRetentionRepository(), RetentionRepository)


def test_fakes_need_no_inheritance() -> None:
    # None of the fakes subclass their Protocol — structural typing only.
    assert MarketDataRepository not in FakeMarketDataRepository.__mro__
    assert ColdTierRepository not in FakeColdTierRepository.__mro__
    assert RetentionRepository not in FakeRetentionRepository.__mro__
