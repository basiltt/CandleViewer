"""candleviewer.statechart — the chart-JSON contract package (ADR-0016).

`registry.py` (E50-T01) is the single loader/validator; `factory.py`
(future ticket) is the only site allowed to import `xstate_statemachine`
(CV-LINT-IMPORT). This `__init__` re-exports the registry's public surface
so callers write `from candleviewer.statechart import Registry` rather than
reaching into the submodule.
"""

from __future__ import annotations

from candleviewer.statechart.errors import (
    DuplicateMachineKeyError,
    MachineNotFoundError,
    MachineSchemaError,
    StatechartRegistryError,
    UnknownKeyError,
    UnresolvedTargetError,
)
from candleviewer.statechart.factory import BuildResult, SyncInterpreterRefusedError, build, restore
from candleviewer.statechart.registry import Registry, export_stately, machine_hash, validate

__all__ = [
    "BuildResult",
    "DuplicateMachineKeyError",
    "MachineNotFoundError",
    "MachineSchemaError",
    "Registry",
    "StatechartRegistryError",
    "SyncInterpreterRefusedError",
    "UnknownKeyError",
    "UnresolvedTargetError",
    "build",
    "export_stately",
    "machine_hash",
    "restore",
    "validate",
]
