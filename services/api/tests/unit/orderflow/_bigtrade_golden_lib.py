"""Shared pieces of the big-trade golden/parity harness (E22-T04). No network, no wall clock.

The golden artefacts live in `packages/fixtures/golden/bigtrade/`; see the README there for the
provenance line and the regeneration procedure (which requires an `ALGO_VERSION` bump)."""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import os
import random
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from candleviewer.domain.primitives import EventId
from candleviewer.exchange.base.models import TradeEvent
from candleviewer.orderflow.bigtrade import BigTradeEngine
from candleviewer.orderflow.bigtrade_models import (
    BigTradeAdvisoryEvent,
    BigTradeConfig,
    BigTradeEvent,
    BigTradeOutput,
    BigTradeThresholdEvent,
    TradeClusterEvent,
)
from tests._corpus import CORPUS_ROOT, TICKS

#: Bump on ANY deliberate change of big-trade output semantics, then regenerate (README).
ALGO_VERSION = "bigtrade-1"
SYMBOL = "BTCUSDT"
TICK = TICKS[SYMBOL]
GOLDEN_DIR = CORPUS_ROOT.parent / "golden" / "bigtrade"
TRADES_GZ = GOLDEN_DIR / "trades_BTCUSDT.csv.gz"
EXPECTED_GZ = GOLDEN_DIR / "expected_BTCUSDT.jsonl.gz"
SUMMARY = GOLDEN_DIR / "summary.json"
REGEN = os.environ.get("CV_REGEN_GOLDEN") == "1"


@dataclass(frozen=True)
class Case:
    name: str
    cfg: BigTradeConfig


CASES: tuple[Case, ...] = (
    Case("notional_250000", BigTradeConfig(mode="notional", value=Decimal("250000"))),
    Case(
        "percentile_99_1h",
        BigTradeConfig(mode="percentile", value=Decimal("99"), percentile_window_ms=3_600_000),
    ),
    Case(
        "notional_100000_cluster_250ms_1tick",
        BigTradeConfig(
            mode="notional",
            value=Decimal("100000"),
            cluster_window_ms=250,
            cluster_tolerance_ticks=1,
        ),
    ),
)


def read_trade_rows() -> list[dict[str, str]]:
    with gzip.open(TRADES_GZ, "rt", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def to_events(
    rows: Sequence[dict[str, str]], symbol: str = SYMBOL, tick: Decimal = TICK
) -> list[TradeEvent]:
    """Same mapping as `ingestion/trade_stream.py` (`notional = price * qty`)."""
    out: list[TradeEvent] = []
    for i, r in enumerate(rows, start=1):
        p, q = Decimal(r["price"]), Decimal(r["qty"])
        out.append(
            TradeEvent.model_validate(
                {
                    "event_id": EventId(uuid.UUID(int=i)),
                    "ts_event": int(r["ts_event_us"]),
                    "ts_ingest": int(r["ts_event_us"]),
                    "source": "replay",
                    "symbol": symbol,
                    "trade_id": r["trade_id"],
                    "price": p,
                    "qty": q,
                    "side": r["side"],
                    "is_block_trade": r["is_block_trade"] == "1",
                    "price_ticks": int((p / tick).to_integral_value()),
                    "notional": p * q,
                    "seq": i,
                }
            )
        )
    return out


def fixture_events() -> list[TradeEvent]:
    return to_events(read_trade_rows())


def run(
    cfg: BigTradeConfig,
    prints: Sequence[TradeEvent],
    seed: int | None = None,
    *,
    flush: bool = True,
    engine: BigTradeEngine | None = None,
) -> list[BigTradeOutput]:
    """Drive the engine; `seed` randomises the batch split (1..40 prints per batch)."""
    eng = engine or BigTradeEngine(SYMBOL, TICK, cfg)
    if seed is None:
        out = eng.process(prints)
    else:
        rng = random.Random(seed)  # noqa: S311 - seeded, reproducible batch splits
        out, i = [], 0
        while i < len(prints):
            n = rng.randint(1, 40)
            out += eng.process(prints[i : i + n])
            i += n
    return out + (list(eng.flush()) if flush else [])


def canon(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def dump(events: Sequence[BigTradeOutput]) -> list[str]:
    """Canonical one-line JSON per event (deterministic: ids are content-derived)."""
    return [canon({"kind": type(e).__name__, **json.loads(e.model_dump_json())}) for e in events]


def digest(lines: Sequence[str]) -> str:
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def split_streams(out: Sequence[BigTradeOutput]) -> dict[str, list[BigTradeOutput]]:
    return {
        "flagged": [e for e in out if isinstance(e, BigTradeEvent)],
        "clusters": [e for e in out if isinstance(e, TradeClusterEvent)],
        "threshold": [e for e in out if isinstance(e, BigTradeThresholdEvent)],
        "advisory": [e for e in out if isinstance(e, BigTradeAdvisoryEvent)],
    }


def engine_state(eng: BigTradeEngine) -> dict[str, object]:
    """Comparable engine state: dedupe ring, threshold/cap state, window sketch read-outs and
    the open-cluster set with the buffered prints."""
    cl = eng._clusters
    win = eng._window
    return {
        "seen": list(eng._seen_order),
        "slot": eng._slot,
        "base": str(eng._base),
        "effective": str(eng._effective),
        "cap": eng._cap,
        "count": win.count,
        "flagged": win.flagged,
        "q_primary": win.quantile(primary=True),
        "q_p80": win.quantile(primary=False),
        "open": [
            (k, c.first.trade_id, c.last.trade_id, c.count, str(c.qty), str(c.notional))
            for k, c in cl._open.items()
        ],
        "buffer": [e.trade_id for e in cl._buffer],
    }


def build_artifacts() -> tuple[dict[str, list[str]], dict[str, object]]:
    """Run the engine for the three cases -> (event lines per case, summary)."""
    prints = fixture_events()
    lines: dict[str, list[str]] = {}
    cases: dict[str, object] = {}
    for case in CASES:
        out = run(case.cfg, prints)
        lines[case.name] = dump(out)
        streams = split_streams(out)
        cases[case.name] = {
            "config": {
                "mode": case.cfg.mode,
                "value": str(case.cfg.value),
                "percentile_window_ms": case.cfg.percentile_window_ms,
                "cluster_window_ms": case.cfg.cluster_window_ms,
                "cluster_tolerance_ticks": case.cfg.cluster_tolerance_ticks,
            },
            "counts": {k: len(v) for k, v in streams.items()},
            "sha256": digest(lines[case.name]),
        }
    summary: dict[str, object] = {
        "algo_version": ALGO_VERSION,
        "symbol": SYMBOL,
        "prints": len(prints),
        "tick_size": str(TICK),
        "cases": cases,
    }
    return lines, summary


def write_expected(lines: dict[str, list[str]], summary: dict[str, object]) -> None:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0, compresslevel=9) as gz:
        for name, ls in lines.items():
            for line in ls:
                rec = canon({"case": name, "event": json.loads(line)})
                gz.write(rec.encode() + b"\n")
    EXPECTED_GZ.write_bytes(buf.getvalue())
    SUMMARY.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_expected() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {c.name: [] for c in CASES}
    with gzip.open(EXPECTED_GZ, "rt", encoding="utf-8") as fh:
        for raw in fh:
            rec = json.loads(raw)
            out[rec["case"]].append(canon(rec["event"]))
    return out


def write_trades_fixture() -> int:
    """(Re)build the compressed trades fixture from the recorded corpus window
    (`ws/clean_publicTrade_BTCUSDT.jsonl`), through the production parser. Never synthesises."""
    from tests.unit.orderflow._bigtrade_helpers import recorded_prints

    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["trade_id", "ts_event_us", "side", "price", "qty", "is_block_trade"])
    for e in sorted(recorded_prints(SYMBOL), key=lambda x: (x.ts_event, x.trade_id)):
        w.writerow([e.trade_id, e.ts_event, e.side, e.price, e.qty, int(e.is_block_trade)])
    raw = io.BytesIO()
    with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, compresslevel=9) as gz:
        gz.write(buf.getvalue().encode())
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    TRADES_GZ.write_bytes(raw.getvalue())
    return len(raw.getvalue())
