"""The single bar emit path (E12-T03): every `BarUpdate` a builder produces, live or replayed,
goes through `EmitRouter.emit`, which hands the same emission, in the same order, to every sink.

Sinks are injected by the composition root, so `bars` gains no import edge: the QuestDB write
path is `WriterSink` around E12-T02's `BarWriter` (structurally typed), and the WS publisher
(E12-T06, not built yet) plugs in as another `BarSink`.

Backpressure policy: `emit` awaits each sink in turn. A slow sink therefore slows the symbol's
fan-out loop, which slows its `NEVER_DROP` bus queue, which backpressures the trade publisher.
Nothing is dropped anywhere on that chain. A sink that raises is counted
(`bar_emit_sink_errors_total{reason=<sink>}`) and logged; the other sinks still get the
emission, and
`CancelledError` is never swallowed.

`generation` is stamped on every emission: 0 for the live series. That matches the
`(bar_param, generation, index)` identity proposed in #2019 and the ADR-0033 rebuild hook. A
rebuild would emit under a higher generation through this same path.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Protocol

import structlog

from candleviewer.bars.metrics import bar_emit_sink_errors_total
from candleviewer.bars.models import Bar, BarSpec, BarUpdate

LIVE_GENERATION: Final = 0


@dataclass(frozen=True, slots=True)
class BarEmission:
    spec: BarSpec
    generation: int
    updates: Sequence[BarUpdate]


class BarSink(Protocol):
    name: str

    async def emit(self, emission: BarEmission) -> None: ...


class BarSubmitter(Protocol):
    """The slice of E12-T02 `BarWriter` this module needs."""

    async def submit(self, bars: Sequence[Bar], spec: BarSpec, *, source: str = ...) -> None: ...


class WriterSink:
    """Persists `close` emissions (amended closes included; DEDUP keeps the last write).

    Forming-bar `open`/`update` emissions are for the live wire only: writing one row per trade
    would multiply the QuestDB write rate by the trade rate for no reader.
    """

    name = "questdb"

    def __init__(self, writer: BarSubmitter) -> None:
        self._writer = writer

    async def emit(self, emission: BarEmission) -> None:
        closed = [u.bar for u in emission.updates if u.kind == "close"]
        if closed:
            await self._writer.submit(closed, emission.spec, source="tape")


class EmitRouter:
    def __init__(self, sinks: Sequence[BarSink]) -> None:
        self._sinks = tuple(sinks)

    async def emit(self, spec: BarSpec, updates: Sequence[BarUpdate], generation: int) -> None:
        emission = BarEmission(spec, generation, updates)
        for sink in self._sinks:
            try:
                await sink.emit(emission)
            except Exception as exc:  # one failing sink must not starve the others
                bar_emit_sink_errors_total.labels(reason=sink.name).inc()
                structlog.get_logger(__name__).warning(
                    "bars_emit_sink_failed",
                    sink=sink.name,
                    spec_hash=spec.spec_hash,
                    error_type=type(exc).__name__,
                )
