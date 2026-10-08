"""BigTradeEngine — per-symbol thresholds, percentile + over-flag cap, clustering (E22-T01).

Binding contract: 24-internal-schemas §2.10. Plain synchronous code (C-2.20). Determinism:
prints are processed in `(ts_event, trade_id)` order (each batch is sorted; the bus delivers a
symbol's batches in order), every window/deadline/refresh boundary is **print time**, and output
envelopes are derived from the triggering print (`ts_event`, `ts_ingest`, a content-derived
UUIDv7-shaped `event_id`), so splitting the same prints into different batches yields identical
output, live and replay alike (R2 exit #1).

Threshold: `absolute_size` compares `qty` with `value`; `notional` compares `price * qty`;
`percentile` uses the trimmed, bucketed P² estimate of the window's notionals
(`quantile.py`), refreshed when a print crosses a 5 s print-time boundary. At every refresh the
over-flag guard checks the fraction of window prints above the **base** threshold. Above 20 %
(with at least `OVERFLAG_MIN_SAMPLES` samples) the cap engages: the effective threshold is raised to
the window p80 (second estimator), prints keep flowing with `capped=True`, and an advisory fires
on entry; leaving the cap and later re-entering emits a fresh advisory (each entry is a new
episode a user should see; `cap_active` on the threshold stream carries the current state).
Percentile mode is cap-eligible only above p80 (at or below it, 20 % flagged is the user's own
choice, not a too-low threshold). A `BigTradeThresholdEvent` is emitted at each refresh
(≤ 1 per 5 s print time) and on config change. Replay (`source="replay"`) compares
threshold/advisory output against the recorded stream instead of re-emitting it (C-2.15)."""

from __future__ import annotations

import hashlib
import time
import uuid
from collections import deque
from collections.abc import Iterable, Sequence
from decimal import Decimal
from typing import Any, Literal

import structlog

from candleviewer.domain.primitives import EventId
from candleviewer.exchange.base.models import TradeEvent
from candleviewer.orderflow import bigtrade_metrics as M
from candleviewer.orderflow import limits as L
from candleviewer.orderflow.bigtrade_cluster import Clusterer, OpenCluster
from candleviewer.orderflow.bigtrade_models import (
    BigTradeAdvisoryEvent,
    BigTradeConfig,
    BigTradeEvent,
    BigTradeOutput,
    BigTradeThresholdEvent,
    CloseReason,
    TradeClusterEvent,
)
from candleviewer.orderflow.quantile import WindowedQuantiles


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


_Q8, _Q6 = Decimal("1e-8"), Decimal("1e-6")
_ENVELOPE_SKIP = frozenset({"event_id", "ts_ingest", "source"})


def _event_id(ts_us: int, *parts: str) -> EventId:
    """Deterministic UUIDv7-shaped id: print-time ms + content hash (no randomness)."""
    rand = int.from_bytes(hashlib.sha256("|".join(parts).encode()).digest()[:10], "big")
    value = ((ts_us // 1000) & 0xFFFFFFFFFFFF) << 80 | rand
    value = (value & ~(0xF << 76)) | (0x7 << 76)
    return EventId(uuid.UUID(int=(value & ~(0x3 << 62)) | (0x2 << 62)))


class BigTradeEngine:
    def __init__(
        self,
        symbol: str,
        tick_size: Decimal,
        config: BigTradeConfig,
        *,
        source: Literal["live", "replay"] = "live",
        recorded: Iterable[BigTradeThresholdEvent | BigTradeAdvisoryEvent] = (),
    ) -> None:
        self.symbol, self.tick_size, self.source = symbol, tick_size, source
        self._label = M.symbol_label(symbol)
        self._m_evaluated = M.bigtrade_prints_evaluated_total.labels(self._label)  # pre-bound
        self._seen: set[str] = set()
        self._seen_order: deque[str] = deque()
        self._recorded = deque(recorded)
        self.replay_mismatches = 0
        self._apply(config.validated())

    def _apply(self, config: BigTradeConfig, *, clusters: Clusterer | None = None) -> None:
        self.config = config
        self._m_flagged = M.bigtrade_flagged_total.labels(self._label, config.mode)  # pre-bound
        # Absolute/notional modes never read the primary quantile: track only the p80 used by
        # the over-flag cap (`primary_q=None` skips the second estimator per slot).
        q = float(config.value) / 100 if config.mode == "percentile" else None
        self._window = WindowedQuantiles(
            q,
            config.percentile_window_ms * 1000,
            L.PERCENTILE_WINDOW_BUCKETS,
            secondary_q=L.OVERFLAG_CAP_QUANTILE,
        )
        self._clusters = clusters or Clusterer(
            self.tick_size,
            config.cluster_window_ms,
            config.cluster_tolerance_ticks,
            on_truncate=lambda: M.bigtrade_state_truncated_total.labels(self._label).inc(),
        )
        # Percentile <= p80 flags >= 20 % BY DEFINITION; capping it would silently and
        # permanently replace the user's choice with p80. The cap guards against a threshold
        # that is *unexpectedly* low, so it applies to percentile mode only above p80.
        self._cap_eligible = config.mode != "percentile" or config.value > Decimal(80)
        self._base: Decimal | None = None if config.mode == "percentile" else config.value
        self._effective = self._base
        self._cap = False
        self._slot: int | None = None

    def reconfigure(self, config: BigTradeConfig, at: TradeEvent) -> list[BigTradeOutput]:
        """Immediate recompute on config change (US-BIG-004 sc.2); `at` is the latest print.
        Clustering replays the buffered prints of the open clusters under the new config
        (`Clusterer.replay`). Threshold state restarts: the window sketch cannot be rebuilt
        from prints it never stored (fixed-size state, SR-E22-05), so a percentile threshold
        re-warms over the new window."""
        config.validated()
        clusters = self._clusters
        closed = clusters.replay(config.cluster_window_ms, config.cluster_tolerance_ticks)
        out: list[BigTradeOutput] = [self._cluster_event(c, r) for c, r in closed]
        self._apply(config, clusters=clusters)
        self._refresh(at)
        out.extend(self._keep(self._threshold_event(at)))
        return out

    def process(self, batch: Sequence[TradeEvent]) -> list[BigTradeOutput]:
        started = time.perf_counter()
        out: list[BigTradeOutput] = []
        evaluated = 0
        for ev in sorted(batch, key=lambda e: (e.ts_event, e.trade_id)):
            if self._accept(ev):
                evaluated += 1
                out.extend(self._evaluate(ev))
        if evaluated:
            self._m_evaluated.inc(evaluated)
        M.bigtrade_eval_latency_seconds.observe(time.perf_counter() - started)
        return out

    def flush(self) -> list[TradeClusterEvent]:
        return [self._cluster_event(c, r) for c, r in self._clusters.flush()]

    def _accept(self, ev: TradeEvent) -> bool:
        if ev.trade_id in self._seen:
            return False  # duplicate after resubscribe: counted once everywhere
        if ev.price <= 0 or ev.qty <= 0 or ev.price % self.tick_size != 0:
            M.bigtrade_input_rejected_total.labels(self._label).inc()  # SR-E22-13
            return False
        self._seen.add(ev.trade_id)
        self._seen_order.append(ev.trade_id)
        if len(self._seen_order) > L.DEDUPE_IDS_MAX:
            self._seen.discard(self._seen_order.popleft())
        return True

    def _measure(self, ev: TradeEvent) -> Decimal:
        return ev.qty if self.config.mode == "absolute_size" else ev.notional

    def _evaluate(self, ev: TradeEvent) -> list[BigTradeOutput]:
        out: list[BigTradeOutput] = []
        slot = ev.ts_event // L.THRESHOLD_REFRESH_US
        measure = self._measure(ev)
        if self._slot is None or slot > self._slot:
            self._slot = slot
            out.extend(self._refresh(ev))
            out.extend(self._keep(self._threshold_event(ev)))
        base_hit = self._base is not None and measure >= self._base
        self._window.add(ev.ts_event, float(measure), flagged=base_hit)
        if self._effective is not None and measure >= self._effective:
            self._m_flagged.inc()
            out.append(self._bigtrade_event(ev))
        out.extend(self._cluster_event(c, r) for c, r in self._clusters.add(ev))
        return out

    def _refresh(self, ev: TradeEvent) -> list[BigTradeOutput]:
        self._window.expire(ev.ts_event)
        if self.config.mode == "percentile":
            est = self._window.quantile(primary=True)
            self._base = None if est is None else Decimal(repr(est)).quantize(_Q8)
        n, flagged = self._window.count, self._window.flagged
        was = self._cap
        p80 = self._window.quantile(primary=False)
        self._cap = (
            self._cap_eligible
            and n >= L.OVERFLAG_MIN_SAMPLES
            and p80 is not None
            and Decimal(flagged) / n > L.OVERFLAG_FRACTION
        )
        self._effective = self._base
        if self._cap and p80 is not None and self._base is not None:
            self._effective = max(self._base, Decimal(repr(p80)).quantize(_Q8))
        if self._cap and not was:
            M.bigtrade_threshold_advisory_total.labels(self._label).inc()
            return self._keep(self._advisory_event(ev, p80 or 0.0))
        return []

    # -- output -----------------------------------------------------------------------------

    def _envelope(self, ev: TradeEvent, kind: str, *key: str) -> dict[str, object]:
        return {
            "event_id": _event_id(ev.ts_event, self.symbol, kind, ev.trade_id, *key),
            "ts_event": ev.ts_event,
            "ts_ingest": ev.ts_ingest,
            "source": self.source,
            "symbol": self.symbol,
        }

    def _flagged_fraction(self) -> Decimal:
        n = self._window.count
        return (Decimal(self._window.flagged) / n).quantize(_Q6) if n else Decimal(0)

    def _bigtrade_event(self, ev: TradeEvent) -> BigTradeEvent:
        threshold = self._effective if self._effective is not None else Decimal(0)
        return BigTradeEvent(
            **self._envelope(ev, "bigtrade"),  # type: ignore[arg-type]  # validated by pydantic
            trade_id=ev.trade_id,
            price=ev.price,
            qty=ev.qty,
            side=ev.side,
            notional=ev.notional,
            price_ticks=ev.price_ticks,
            mode=self.config.mode,
            threshold_abs=threshold,
            capped=self._cap,
            estimated=self.config.mode == "percentile",
            seq=ev.seq,
        )

    def _threshold_event(self, ev: TradeEvent) -> BigTradeThresholdEvent:
        c = self.config
        return BigTradeThresholdEvent(
            **self._envelope(ev, "threshold", str(self._slot)),  # type: ignore[arg-type]
            mode=c.mode,
            value=c.value,
            percentile_window_ms=c.percentile_window_ms,
            cluster_window_ms=c.cluster_window_ms,
            cluster_tolerance_ticks=c.cluster_tolerance_ticks,
            effective_threshold_abs=(
                self._effective if self._effective is not None else Decimal(0)
            ),
            cap_active=self._cap,
            sample_count=self._window.count,
            flagged_fraction=self._flagged_fraction(),
            estimated=c.mode == "percentile",
        )

    def _advisory_event(self, ev: TradeEvent, p80: float) -> BigTradeAdvisoryEvent:
        base = self._base if self._base is not None else Decimal(0)
        return BigTradeAdvisoryEvent(
            **self._envelope(ev, "advisory"),  # type: ignore[arg-type]
            reason="threshold_too_low",
            mode=self.config.mode,
            threshold_abs=base,
            flagged_fraction=self._flagged_fraction(),
            suggested_value=self._suggest(p80),
            cap_active=True,
        )

    def _suggest(self, p80: float) -> Decimal:
        """Suggested `value` in the configured mode's unit (§2.10). absolute/notional: the window
        p80, which flags <= 20 %. Percentile (only cap-eligible above 80): the configured value
        is kept, since raising it cannot fix a distribution shift inside the window; the cap
        (p80) is the legibility remedy, and `cap_active` reports it."""
        if self.config.mode == "percentile":
            return self.config.value
        return Decimal(repr(p80)).quantize(_Q8)

    def _cluster_event(self, cluster: OpenCluster, reason: CloseReason) -> TradeClusterEvent:
        M.bigtrade_clusters_emitted_total.labels(self._label).inc()
        first, last = cluster.first, cluster.last
        side, bucket = cluster.key
        return TradeClusterEvent(
            **self._envelope(last, "cluster", first.trade_id),  # type: ignore[arg-type]
            cluster_id=f"{side}:{bucket}:{first.trade_id}",
            side=side,
            price_bucket=bucket,
            anchor_price=first.price,
            first_ts_event=first.ts_event,
            last_ts_event=last.ts_event,
            trade_id_count=cluster.count,
            first_trade_id=first.trade_id,
            last_trade_id=last.trade_id,
            trade_ids=tuple(cluster.ids),
            trade_ids_truncated=cluster.count > len(cluster.ids),
            cluster_size=cluster.count,
            total_qty=cluster.qty,
            total_notional=cluster.notional.quantize(_Q8),
            vwap=(cluster.notional / cluster.qty).quantize(_Q8),
            max_print_qty=cluster.max_qty,
            close_reason=reason,
        )

    def _keep(self, ev: BigTradeThresholdEvent | BigTradeAdvisoryEvent) -> list[BigTradeOutput]:
        """Live: publish. Replay: compare with the recorded stream, never republish (C-2.15)."""
        if self.source == "live":
            return [ev]
        expected = self._recorded.popleft() if self._recorded else None
        if expected is None or _semantic(expected) != _semantic(ev):
            self.replay_mismatches += 1
            M.bigtrade_replay_mismatch_total.labels(self._label).inc()
            _log().warning("bigtrade.replay_mismatch", symbol=self.symbol, kind=type(ev).__name__)
        return []


def _semantic(ev: BigTradeThresholdEvent | BigTradeAdvisoryEvent) -> dict[str, object]:
    return {"kind": type(ev).__name__, **ev.model_dump(exclude=set(_ENVELOPE_SKIP))}
