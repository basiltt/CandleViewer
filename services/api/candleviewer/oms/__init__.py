"""oms module (M14).

Order state machine, fan-out, brackets, emulated OCO/iceberg/TWAP/chase,
reconciliation, SL invariant.

Public interface only — internal implementation modules are not re-exported.
Allowed dependencies (CONSTITUTION.md C-3.1): M1, M3, M4, M5, M10, M13, M17.

This module is mostly a conforming EMPTY scaffold (E02-T05); real order
logic lands in the epic that owns this module (see
docs/plan/20-architecture.md Sec.3 and the module table in
CONSTITUTION.md Sec.3). `Validator`/`ReadOnlyCheck` (E09-T04) is the one
exception, always-on ahead of the rest of OMS: it is the boundary every
future order-placement path must call before accepting a position-opening
command, so the read-only degradation invariant exists from day one rather
than being retrofitted once OMS lands.
"""

from __future__ import annotations

from .validator import OrderPlacementRefused, ReadOnlyCheck, Validator

__all__: list[str] = ["OrderPlacementRefused", "ReadOnlyCheck", "Validator"]
