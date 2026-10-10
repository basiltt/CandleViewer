"""Recorded-day golden bar files for the determinism harness (E12-T04, BI-4).

Fixture day: the recorded-corpus BTCUSDT trade tape already used by the time-bar golden test
(`tests.unit.bars.test_time_builder_golden.CORPUS`), 542 public prints, 3 h, tick 0.1; provenance
in `packages/fixtures/golden/bars/determinism/README.md`. It is decoded only through the
exchange adapter's production parser via `tests._corpus` (C-2.2): this module never touches
venue field names, topics or paths.
Its sha256 is pinned in `manifest.json`, so a changed fixture fails the golden test, not silently
moves the goldens.

One file per builder kind/parameter (`<label>.jsonl`, one canonical `comparator.line` per bar).
Regeneration is deliberate and never implicit:
- only `python -m bench.bar_determinism.regen_goldens --write --reason "<why>"` writes files;
- it refuses to run under CI (`CI` env set) and refuses when a kind's output changed but its
  `BUILD_VERSIONS` entry (`candleviewer/bars/rows.py`) equals the one recorded in the manifest,
  so the regenerated files and the `build_version` bump land in the same commit;
- the golden test also fails when `BUILD_VERSIONS` moved without a regeneration.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from candleviewer.bars.models import BarSpec
from candleviewer.bars.rows import BUILD_VERSIONS
from candleviewer.exchange.base.models import TradeEvent
from candleviewer.exchange.base.trade_print import TradePrint
from tests import _corpus
from tests.unit.bars.test_time_builder_golden import CORPUS

from . import comparator, invariants
from .generator import TICK

_EID = uuid.UUID(int=0xE12F)

REPO = Path(__file__).resolve().parents[4]
GOLDEN_DIR = REPO / "packages" / "fixtures" / "golden" / "bars" / "determinism"
MANIFEST = GOLDEN_DIR / "manifest.json"
FIXTURE = _corpus.corpus_path(CORPUS)

#: Golden matrix: every builder kind, the parameters the recorded day exercises.
GOLDEN_SPECS: dict[str, BarSpec] = {
    "time-1m": BarSpec(kind="time", interval_ms=60_000),
    "time-5m": BarSpec(kind="time", interval_ms=300_000),
    "tick-50": BarSpec(kind="tick", tick_count=50),
    "volume-5": BarSpec(kind="volume", volume_threshold=Decimal(5)),
    "volume-0.25": BarSpec(kind="volume", volume_threshold=Decimal("0.25")),
    "range-20": BarSpec(kind="range", range_ticks=20),
    "delta-1": BarSpec(kind="delta", delta_threshold=Decimal(1)),
    "renko-10": BarSpec(kind="renko", range_ticks=10),
    "renko-10-wick-rev3": BarSpec(kind="renko", range_ticks=10, renko_wick=True, reversal_bricks=3),
}


def fixture_sha256() -> str:
    return hashlib.sha256(FIXTURE.read_bytes()).hexdigest()


def load_tape() -> list[TradeEvent]:
    """The fixture day as `TradeEvent`s, in file order (`seq` = position), decoded by the
    adapter's parser. Anything that is not a trade print is an error, not silently skipped."""
    out: list[TradeEvent] = []
    for frame in _corpus.frames(CORPUS):
        for p in _corpus.normalize(frame):
            if not isinstance(p, TradePrint):
                raise TypeError(f"unexpected event in the fixture day: {type(p).__name__}")
            out.append(
                TradeEvent.model_construct(
                    schema_version=1,
                    event_id=_EID,
                    ts_event=p.ts_event_us,
                    ts_ingest=p.ts_event_us,
                    source="replay",
                    category="linear",
                    symbol=p.symbol,
                    trade_id=p.trade_id,
                    price=p.price,
                    qty=p.qty,
                    side=p.side,
                    is_block_trade=p.is_block_trade,
                    price_ticks=int(p.price / TICK),
                    notional=p.price * p.qty,
                    seq=len(out),
                )
            )
    return out


def render(spec: BarSpec, tape: list[TradeEvent]) -> list[str]:
    return [comparator.line(b) for b in invariants.run(invariants.make_builder, spec, tape)]


def path(label: str) -> Path:
    return GOLDEN_DIR / f"{label}.jsonl"


def read(label: str) -> list[str]:
    return path(label).read_text(encoding="utf-8").splitlines()


def load_manifest() -> dict[str, object]:
    doc: dict[str, object] = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return doc


@dataclass(frozen=True)
class RegenPlan:
    changed: dict[str, list[str]]  # label -> new lines
    unbumped: list[str]  # kinds whose output changed but whose build_version did not move


def plan(tape: list[TradeEvent]) -> RegenPlan:
    """What a regeneration would change, and whether the build_version rule allows it."""
    recorded: dict[str, int] = {}
    if MANIFEST.exists():
        bv = load_manifest().get("build_versions", {})
        recorded = dict(bv) if isinstance(bv, dict) else {}
    changed: dict[str, list[str]] = {}
    for label, spec in GOLDEN_SPECS.items():
        lines = render(spec, tape)
        if not path(label).exists() or read(label) != lines:
            changed[label] = lines
    kinds = sorted({GOLDEN_SPECS[label].kind for label in changed})
    unbumped: list[str] = [
        str(k) for k in kinds if k in recorded and recorded[k] == BUILD_VERSIONS[k]
    ]
    return RegenPlan(changed, unbumped)


def write(p: RegenPlan, reason: str) -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    for label, lines in p.changed.items():
        path(label).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    doc = {
        "fixture": str(FIXTURE.relative_to(REPO).as_posix()),
        "fixture_sha256": fixture_sha256(),
        "build_versions": dict(sorted(BUILD_VERSIONS.items())),
        "specs": {k: v.spec_hash for k, v in GOLDEN_SPECS.items()},
        "reason": reason,
    }
    MANIFEST.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8", newline="\n")
