"""Domain errors for the `statechart` registry (E50-T01).

`candleviewer.statechart.registry` never imports `xstate_statemachine`
(CV-LINT-IMPORT) — it is the pre-`create_machine` gate, not a runtime. These
exceptions are the single vocabulary the registry raises so callers (the
future `factory.py`) can catch one base type.
"""

from __future__ import annotations


class StatechartRegistryError(Exception):
    """Base exception for the `candleviewer.statechart.registry` module."""


class MachineNotFoundError(StatechartRegistryError):
    """Raised when a requested machine key has no `machines/*.machine.json`."""


class MachineSchemaError(StatechartRegistryError):
    """Raised when a chart fails JSON-Schema (2020-12) structural validation."""


class UnknownKeyError(StatechartRegistryError):
    """Raised by the recursive `KNOWN_MACHINE_KEYS` walk (CV-C57).

    Covers every node in the tree, including nodes reachable only through an
    inline `invoke.src` machine definition — the one gap the upstream
    library's own recursive check (round 12, `validate_top_level_keys`)
    leaves open (28-statechart-catalogue.md §1.3b, "Q-5").
    """


class UnresolvedTargetError(StatechartRegistryError):
    """Raised when a transition `target` is relative or does not resolve.

    Runs *before* `create_machine` ever sees the chart, so a bad target is a
    registry-time failure, not a `strictTargets` runtime one (belt-and-braces
    per the ticket's technical notes).
    """


class DuplicateMachineKeyError(StatechartRegistryError):
    """Raised when two `machines/*.machine.json` files declare the same key."""
