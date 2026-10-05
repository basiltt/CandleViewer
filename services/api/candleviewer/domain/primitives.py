"""Domain primitives (`docs/plan/24-internal-schemas.md` §1.2-1.4).

Time/price/qty aliases, identifiers, symbol/environment literals and the
base event envelope. Owned by no single module — every module may import
this package (it has no dependencies of its own and carries zero exchange
vocabulary, C-2.2). This is the module the exchange port
(`candleviewer.exchange.base.models`) is specified against in
`docs/plan/24-internal-schemas.md` §14.1.

Verbatim transcription of §1.2; do not add fields here without updating that
section in the same PR (DoD: "`24-internal-schemas.md` §14 updated if the
shipped shape diverged").
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal, NewType
from uuid import UUID

from pydantic import StringConstraints

type TsUs = int
"""Microseconds since the Unix epoch, UTC (C4). The exchange millisecond fields are
multiplied by 1000 at the adapter boundary; `datetime` appears only in
Postgres rows and human-facing strings."""

type TsMs = int
"""Milliseconds — adapter boundary only; never crosses into domain events."""

type Ticks = int
"""Integer price levels from `price_origin`."""

type Px = Decimal
"""Price — always `Decimal`, never `float` (C-2.2 pricing rule)."""

type Qty = Decimal
"""Quantity, base units (contracts)."""

type Notional = Decimal
"""Quote-currency (USDT) notional value."""

type Bps = Decimal
"""Basis points."""

EventId = NewType("EventId", UUID)
"""UUID7 — time-sortable event identifier."""

OrderId = NewType("OrderId", UUID)
GroupId = NewType("GroupId", UUID)
AccountId = NewType("AccountId", UUID)
UserId = NewType("UserId", UUID)
RuleId = NewType("RuleId", UUID)

Symbol = Annotated[str, StringConstraints(pattern=r"^[A-Z0-9]{4,20}$")]
OrderLinkId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,36}$")]
Exchange = Literal["bybit"]
Category = Literal["linear"]
Environment = Literal["live", "demo", "testnet"]
"""The value that crosses the wire; identical to the OpenAPI `Environment`
schema and the Postgres `exchange_env` type (contract test
`enum_parity_environment`)."""

ExecutionMode = Literal["exchange", "paper", "replay"]
"""Internal only; never serialised as `environment`. Orthogonal to
`Environment` — see §1.2 for the paper/replay/live cross-product rationale."""

Side = Literal["buy", "sell"]
