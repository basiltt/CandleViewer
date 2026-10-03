"""MetricDescriptor / MetricRegistry (24-internal-schemas.md 7.1, 7.3).

The single named registry the rule vocabulary projects from. Producers
(E12/E18-E25) register their descriptors; this module only describes them.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Literal

from pydantic import BaseModel, ConfigDict

Unit = Literal[
    "price", "qty", "notional", "ratio", "pct", "bps", "count", "ms", "zscore", "enum", "bool"
]
ValueType = Literal["number", "bool", "enum", "series"]
Input = Literal[
    "trades", "book", "bars", "positions", "orders", "wallet", "liquidations", "oi", "funding"
]
#: Inputs that exist only for symbols on the recorded-symbol list (tick-level data).
RECORDED_INPUTS: frozenset[str] = frozenset({"trades", "book", "liquidations"})


class MetricDescriptor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    title: str
    unit: Unit
    value_type: ValueType = "number"
    enum_values: tuple[str, ...] = ()
    scope: Literal["symbol", "position", "account", "global"] = "symbol"
    inputs: tuple[Input, ...] = ()
    params: dict[str, str] = {}  # name -> default (prose)
    warmup_bars: int = 0
    cadence: Literal["on_trade", "on_book", "on_bar_close", "on_timer", "on_fill"] = "on_bar_close"
    nullable_when: str = ""
    deterministic: bool = True
    confidence: Literal["exact", "estimated"] = "exact"


class DuplicateMetricError(ValueError):
    pass


class MetricRegistry:
    def __init__(self, descriptors: Iterable[MetricDescriptor] = ()) -> None:
        self._by_name: dict[str, MetricDescriptor] = {}
        for d in descriptors:
            self.register(d)

    def register(self, d: MetricDescriptor) -> None:
        if d.name in self._by_name:
            raise DuplicateMetricError(f"metric {d.name!r} already registered")
        self._by_name[d.name] = d

    def get(self, name: str) -> MetricDescriptor | None:
        return self._by_name.get(name)

    def names(self) -> list[str]:
        return sorted(self._by_name)

    def __iter__(self) -> Iterator[MetricDescriptor]:
        return iter(self._by_name[n] for n in sorted(self._by_name))

    def __len__(self) -> int:
        return len(self._by_name)
