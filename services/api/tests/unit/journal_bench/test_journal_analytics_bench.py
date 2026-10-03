"""E41-K01: the bench generator is deterministic and the query builder cannot widen RBAC scope."""

from __future__ import annotations

import pytest

from bench.journal_analytics import generate as g
from bench.journal_analytics import queries as q

GRANTED = [str(a) for a in g.account_ids()[:2]]
OTHER = str(g.account_ids()[5])


def test_generate_is_seeded_and_shaped() -> None:
    a, b = g.generate(200), g.generate(200)
    assert a.trades == b.trades and a.trade_tags == b.trade_tags
    assert len(a.trade_tags) == 200 * g.TAGS_PER_TRADE
    assert len({t[1] for t in a.trades}) <= g.N_ACCOUNTS


def test_scoped_from_requested_cannot_widen_scope() -> None:
    src = q.scoped_from(GRANTED, [GRANTED[0], OTHER])
    assert OTHER not in src and GRANTED[0] in src


def test_scoped_from_disjoint_request_returns_nothing() -> None:
    assert "WHERE false" in q.scoped_from(GRANTED, [OTHER])


def test_scoped_from_rejects_non_uuid_ids() -> None:
    with pytest.raises(ValueError):
        q.scoped_from(["x'; DROP TABLE journal_trades;--"])


def test_every_breakdown_query_goes_through_scope() -> None:
    src = q.scoped_from(GRANTED)
    for sql in q.all_breakdowns(src):
        assert src in sql
