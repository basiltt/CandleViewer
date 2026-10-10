"""Seeded synthetic `TradeEvent` tapes for the bar determinism harness (E12-T04).

Offline by construction: this module imports only the standard library and the domain model
(a test asserts the import set), it produces in-memory objects and has no I/O, so it cannot be
pointed at an exchange. The seed is the whole repro: `generate(GenConfig(seed=s, n=...))` is a
pure function of its config.

Prices are integer ticks (`tick`), sizes integer lots (`lot`), converted to `Decimal` exactly
once per trade. Adversarial patterns (each with its own probability):
- `huge`: one print spanning several volume thresholds;
- `exact`: a print of exactly `threshold_lots`, or a timestamp exactly on a time boundary;
- `reversal`: a burst of alternating multi-brick price jumps;
- `silence`: a gap of several minutes (empty time intervals);
- `late`: a timestamp up to `late_max_us` behind the watermark (some beyond the 60 s window);
- `duplicate`: the previous trade re-sent with the same `trade_id` (new ingest `seq`).
"""

from __future__ import annotations

import random
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal

from candleviewer.exchange.base.models import TradeEvent

SYMBOL = "BTCUSDT"
TICK = Decimal("0.1")
LOT = Decimal("0.001")
_EID = uuid.UUID(int=0xE12)
_T0_US = 1_700_000_000_000_000


@dataclass(frozen=True)
class GenConfig:
    seed: int = 12004
    n: int = 100_000
    start_px_ticks: int = 631_200
    vol_ticks: float = 1.6  # stdev of the per-trade price step, in ticks
    mean_dt_us: int = 86_000  # ~1M trades per day
    size_dist: str = "lognormal"  # "lognormal" | "pareto" | "uniform"
    size_scale_lots: int = 40
    buy_skew: float = 0.0  # P(buy) = 0.5 + skew
    threshold_lots: int = 5_000  # the volume threshold the "huge"/"exact" prints aim at
    boundary_us: int = 60_000_000  # the time interval the "exact" timestamps aim at
    jump_ticks: int = 30  # reversal / jump size, a few renko bricks
    p_huge: float = 0.0005
    p_exact: float = 0.001
    p_reversal: float = 0.0005
    p_silence: float = 0.0002
    p_late: float = 0.002
    late_max_us: int = 90_000_000
    p_duplicate: float = 0.001


def _size(rng: random.Random, cfg: GenConfig) -> int:
    if cfg.size_dist == "pareto":
        return max(1, int(cfg.size_scale_lots * (rng.paretovariate(1.6) - 0.9)))
    if cfg.size_dist == "uniform":
        return rng.randint(1, 2 * cfg.size_scale_lots)
    return max(1, int(rng.lognormvariate(0.0, 1.2) * cfg.size_scale_lots / 2))


def _event(seq: int, ts: int, px: int, lots: int, buy: bool, tid: str) -> TradeEvent:
    price = Decimal(px) * TICK
    qty = Decimal(lots) * LOT
    return TradeEvent.model_construct(
        schema_version=1,
        event_id=_EID,
        ts_event=ts,
        ts_ingest=ts,
        source="replay",
        category="linear",
        symbol=SYMBOL,
        trade_id=tid,
        price=price,
        qty=qty,
        side="buy" if buy else "sell",
        is_block_trade=False,
        price_ticks=px,
        notional=price * qty,
        seq=seq,
    )


def iter_trades(cfg: GenConfig) -> Iterator[TradeEvent]:
    """Yield `cfg.n` trades; deterministic for a given `cfg`."""
    rng = random.Random(cfg.seed)  # noqa: S311 - reproducible test data, not crypto
    px, ts, watermark = cfg.start_px_ticks, _T0_US, _T0_US
    reversal_left, reversal_sign = 0, 1
    prev: TradeEvent | None = None
    for seq in range(cfg.n):
        r = rng.random()
        if prev is not None and r < cfg.p_duplicate:
            yield prev.model_copy(update={"seq": seq})
            continue
        lots = _size(rng, cfg)
        ts = watermark + int(rng.expovariate(1.0 / cfg.mean_dt_us))
        step = round(rng.gauss(0.0, cfg.vol_ticks))
        if reversal_left:
            step, reversal_sign = reversal_sign * cfg.jump_ticks, -reversal_sign
            reversal_left -= 1
        else:
            r = rng.random()
            if r < cfg.p_huge:
                lots = cfg.threshold_lots * rng.randint(2, 6) + rng.randint(0, 3)
            elif r < cfg.p_huge + cfg.p_exact:
                lots = cfg.threshold_lots
                ts = -(-ts // cfg.boundary_us) * cfg.boundary_us  # exactly on a boundary
            elif r < cfg.p_huge + cfg.p_exact + cfg.p_reversal:
                reversal_left, reversal_sign = rng.randint(3, 8), rng.choice((1, -1))
            elif r < cfg.p_huge + cfg.p_exact + cfg.p_reversal + cfg.p_silence:
                ts += rng.randint(2, 10) * cfg.boundary_us
            elif r < cfg.p_huge + cfg.p_exact + cfg.p_reversal + cfg.p_silence + cfg.p_late:
                ts = watermark - rng.randint(1, cfg.late_max_us)
        px = max(1_000, px + step)
        watermark = max(watermark, ts)
        buy = rng.random() < 0.5 + cfg.buy_skew
        prev = _event(seq, ts, px, lots, buy, f"{cfg.seed:x}-{seq:x}")
        yield prev


def generate(cfg: GenConfig) -> list[TradeEvent]:
    return list(iter_trades(cfg))
