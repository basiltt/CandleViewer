"""candleviewer.statechart.upcasters — the upcaster registry (E50-T02).

Keyed `(machine, from_hash) -> to_hash` plus the callable that migrates a
persisted snapshot context/value from the old chart shape to the new one.
`lock.diff()` (this ticket) consults `has_upcaster()` to decide whether a
`machine_hash` drift is *covered*; `statechart.persistence.restore()`
(E50-T10/T49) will consult `get_upcaster()` at restore time to actually run
the migration on an old snapshot. Only the registry lives here — nothing in
this module imports `xstate_statemachine` (CV-LINT-IMPORT).

**No-op upcasters are refused** (ticket acceptance criterion 2): an upcaster
that returns its input dict unchanged is exactly the shape a lazy "just
silence CI" fix would take, so `register_upcaster()` runs a self-check
against a constructed non-trivial input the moment the upcaster is
registered — a no-op body a golden-snapshot test would also have caught,
but this catches it at import time instead of waiting on a specific test
file existing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

#: An upcaster migrates a persisted-snapshot context dict from the old
#: chart shape to the new one. Pure, synchronous, no I/O (CV-C58: restore
#: happens before `start()`, off any event loop concern).
UpcasterFn = Callable[[dict[str, Any]], dict[str, Any]]


class NoOpUpcasterError(Exception):
    """Raised when a registered upcaster returns its input unchanged on the
    self-check probe (ticket acceptance criterion 2, MUSTNOT-09)."""


class UpcasterKeyError(Exception):
    """Raised on a duplicate or unknown `(machine, from_hash)` registration
    or lookup."""


@dataclass(frozen=True, slots=True)
class _UpcasterEntry:
    to_hash: str
    fn: UpcasterFn


#: `(machine, from_hash) -> _UpcasterEntry`.
_REGISTRY: dict[tuple[str, str], _UpcasterEntry] = {}

#: The self-check probe context: deliberately non-trivial (several keys,
#: nested structure, a list) so a no-op *or* a shallow/partial upcaster
#: (one that copies the dict but forgets a nested field) both have a
#: fighting chance of being caught — though the exhaustive check remains
#: the golden-snapshot test the ticket requires per upcaster.
_PROBE_CONTEXT: dict[str, Any] = {
    "cv_probe_marker": "e50t02-noop-upcaster-probe",
    "nested": {"a": 1, "b": [1, 2, 3]},
    "list": ["x", "y"],
}


def _assert_not_noop(machine: str, from_hash: str, to_hash: str, fn: UpcasterFn) -> None:
    probe = dict(_PROBE_CONTEXT)
    result = fn(probe)
    if result == _PROBE_CONTEXT:
        raise NoOpUpcasterError(
            f"upcaster for {machine!r} {from_hash} -> {to_hash} returned its "
            "input unchanged on the self-check probe context; a no-op "
            "upcaster is refused (MUSTNOT-09) — it must actually transform "
            "the snapshot context"
        )


def register_upcaster(machine: str, from_hash: str, to_hash: str, fn: UpcasterFn) -> None:
    """Register *fn* as the migration for `machine` snapshots taken at
    `from_hash`, bringing them to the shape `to_hash` expects.

    Raises `UpcasterKeyError` on a duplicate `(machine, from_hash)` pair
    (one upcaster per source hash — chaining is expressed as multiple
    registered hops, never overwritten in place) and `NoOpUpcasterError`
    if `fn` fails the no-op self-check.
    """
    key = (machine, from_hash)
    if key in _REGISTRY:
        raise UpcasterKeyError(
            f"an upcaster is already registered for {machine!r} from {from_hash}"
        )
    _assert_not_noop(machine, from_hash, to_hash, fn)
    _REGISTRY[key] = _UpcasterEntry(to_hash=to_hash, fn=fn)


def has_upcaster(machine: str, from_hash: str, to_hash: str) -> bool:
    """True iff an upcaster is registered for exactly this hash transition
    (`lock.diff()`'s coverage check — both hashes must match, not just the
    source, so relabelling an upcaster's declared destination is itself a
    drift the lock diff would still catch)."""
    entry = _REGISTRY.get((machine, from_hash))
    return entry is not None and entry.to_hash == to_hash


def get_upcaster(machine: str, from_hash: str) -> UpcasterFn:
    entry = _REGISTRY.get((machine, from_hash))
    if entry is None:
        raise UpcasterKeyError(f"no upcaster registered for {machine!r} from {from_hash}")
    return entry.fn


def registered_keys() -> list[tuple[str, str]]:
    """Every `(machine, from_hash)` pair currently registered, sorted —
    test/tooling introspection only."""
    return sorted(_REGISTRY.keys())
