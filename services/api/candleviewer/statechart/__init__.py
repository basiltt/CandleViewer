"""candleviewer.statechart — the chart-JSON contract package (ADR-0016).

`registry.py` (E50-T01) is the single loader/validator; `factory.py`
is the only site allowed to import `xstate_statemachine` (CV-LINT-IMPORT).
`lock.py` / `upcasters.py` (E50-T02) are the machine_hash lock diff and
upcaster registry, also import-free of the runtime. This `__init__`
re-exports the public surface so callers write
`from candleviewer.statechart import Registry` rather than reaching into
the submodule.
"""

from __future__ import annotations

import candleviewer.statechart.book_upcasters  # registers B14 upcaster (#2204)
import candleviewer.statechart.session_upcasters  # noqa: F401  (registers B16 upcaster)
from candleviewer.statechart.config import SNAPSHOT_V
from candleviewer.statechart.errors import (
    DuplicateMachineKeyError,
    MachineNotFoundError,
    MachineSchemaError,
    StatechartRegistryError,
    UnknownKeyError,
    UnresolvedTargetError,
)
from candleviewer.statechart.factory import BuildResult, SyncInterpreterRefusedError, build, restore
from candleviewer.statechart.lock import (
    DriftFinding,
    LockFileError,
    check_removed,
    diff,
    load_lock,
    render_lock,
)
from candleviewer.statechart.registry import Registry, export_stately, machine_hash, validate
from candleviewer.statechart.upcasters import (
    NoOpUpcasterError,
    UpcasterKeyError,
    get_upcaster,
    has_upcaster,
    register_upcaster,
    registered_keys,
)

__all__ = [
    "SNAPSHOT_V",
    "BuildResult",
    "DriftFinding",
    "DuplicateMachineKeyError",
    "LockFileError",
    "MachineNotFoundError",
    "MachineSchemaError",
    "NoOpUpcasterError",
    "Registry",
    "StatechartRegistryError",
    "SyncInterpreterRefusedError",
    "UnknownKeyError",
    "UnresolvedTargetError",
    "UpcasterKeyError",
    "build",
    "check_removed",
    "diff",
    "export_stately",
    "get_upcaster",
    "has_upcaster",
    "load_lock",
    "machine_hash",
    "register_upcaster",
    "registered_keys",
    "render_lock",
    "restore",
    "validate",
]
