# ruff: noqa: S311  # seeded non-crypto RNG is the point: reproducible synthetic data
"""Seeded synthetic ``journal_trades`` / ``journal_trade_tags`` generator (E41-K01).

Synthetic only: no production/demo data. ~40 tags, ~3 tags/trade, 6 accounts. Values are
Decimal with 18 fractional digits so numeric(38,18) aggregation cost is really measured.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

N_ACCOUNTS = 6
N_TAGS = 40
TAGS_PER_TRADE = 3
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "BNBUSDT", "ADAUSDT", "LINKUSDT")
SETUPS = ("breakout", "pullback", "reversal", "range-fade", "trend", "news")
SPAN_DAYS = 730
END = datetime(2026, 9, 30, tzinfo=UTC)
_Q = Decimal(10) ** -18


def _uid(ns: str, i: int) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"cv-bench/{ns}/{i}")


def account_ids() -> list[uuid.UUID]:
    return [_uid("acct", i) for i in range(N_ACCOUNTS)]


def tag_ids() -> list[uuid.UUID]:
    return [_uid("tag", i) for i in range(N_TAGS)]


@dataclass(frozen=True)
class Dataset:
    trades: list[tuple[object, ...]]
    trade_tags: list[tuple[uuid.UUID, uuid.UUID]]


TRADE_COLUMNS = (
    "id exchange_account_id symbol side opened_at closed_at hold_seconds realised_pnl "
    "fees_paid funding_paid r_multiple mae_r mfe_r outcome setup_name is_aggregate"
).split()


def generate(n: int, seed: int = 41) -> Dataset:
    """Deterministic for a given ``(n, seed)``."""
    rng = random.Random(seed)
    accts, tags = account_ids(), tag_ids()
    trades: list[tuple[object, ...]] = []
    links: list[tuple[uuid.UUID, uuid.UUID]] = []
    step = timedelta(days=SPAN_DAYS) / max(n, 1)
    for i in range(n):
        tid = _uid("trade", i)
        opened = (
            END - timedelta(days=SPAN_DAYS) + step * i + timedelta(seconds=rng.randint(0, 3000))
        )
        hold = rng.randint(30, 6 * 3600)
        r = rng.gauss(0.15, 1.4)
        risk = Decimal(rng.randint(20, 400))
        pnl = (Decimal(repr(r)) * risk).quantize(_Q)
        fees = Decimal(repr(rng.uniform(0.05, 4.0))).quantize(_Q)
        funding = Decimal(repr(rng.uniform(-0.5, 1.0))).quantize(_Q)
        outcome = "win" if pnl - fees - funding > 0 else "loss"
        trades.append(
            (
                tid,
                rng.choice(accts),
                rng.choice(SYMBOLS),
                rng.choice(("long", "short")),
                opened,
                opened + timedelta(seconds=hold),
                hold,
                pnl,
                fees,
                funding,
                Decimal(repr(r)).quantize(Decimal("0.000001")),
                Decimal(repr(-abs(rng.gauss(0.6, 0.5)))).quantize(Decimal("0.000001")),
                Decimal(repr(abs(rng.gauss(1.2, 1.0)))).quantize(Decimal("0.000001")),
                outcome,
                rng.choice(SETUPS),
                False,
            )
        )
        for t in rng.sample(tags, TAGS_PER_TRADE):
            links.append((tid, t))
    return Dataset(trades, links)
