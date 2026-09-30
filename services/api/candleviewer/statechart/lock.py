"""candleviewer.statechart.lock — machine_hash lock diffing (E50-T02).

`machine_hashes.lock` (committed alongside `machines/*.machine.json`) is the
single source of truth for "what hash did we last accept for this machine".
This module is the pure, side-effect-free diff: given a `Registry` (already
loaded + validated, `registry.py`, E50-T01) and a parsed lock-file mapping,
it says which machines are new, unchanged, or drifted — and, for a drifted
machine, whether the drift is *covered* (a version bump plus a registered
upcaster in `upcasters.py`) or *uncovered* (MUST-12/MUSTNOT-09: fails CI).

Deliberately never imports `xstate_statemachine` (CV-LINT-IMPORT): the lock
diff is computed entirely from `registry.hash()` (sha256 of canonical JSON)
and the upcaster registry's plain dict, both of which are also import-free.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from candleviewer.statechart.registry import Registry
from candleviewer.statechart.upcasters import has_upcaster

DEFAULT_LOCK_PATH = Path(__file__).resolve().parent / "machines" / "machine_hashes.lock"

#: Lock-file top-level shape: `{"machines": {"<key>": {"hash": "<sha256>",
#: "version": <int>}}}`. `version` here is the *chart's* declared `version`
#: key (schema.py allows an optional integer `version`), not the snapshot
#: envelope version (`config.SNAPSHOT_V`) — the two are deliberately
#: separate counters (a chart can be re-versioned without touching the
#: snapshot envelope layout, and vice versa).
LOCK_SCHEMA_VERSION = 1


class LockFileError(Exception):
    """Raised on a malformed `machine_hashes.lock` (bad JSON / bad shape)."""


@dataclass(frozen=True, slots=True)
class DriftFinding:
    """One machine whose `machine_hash` no longer matches the lock file."""

    machine: str
    locked_hash: str
    current_hash: str
    locked_version: int | None
    current_version: int | None
    covered: bool
    reason: str

    def format(self) -> str:
        status = "covered by upcaster + version bump" if self.covered else "UNCOVERED"
        return (
            f"{self.machine}: hash drift {self.locked_hash} -> {self.current_hash} "
            f"(version {self.locked_version} -> {self.current_version}) [{status}]: "
            f"{self.reason}"
        )


def load_lock(path: Path) -> dict[str, dict[str, Any]]:
    """Return the `machines` mapping from *path*, or `{}` if the file does
    not exist yet (a brand-new repo/registry has no lock to diff against)."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LockFileError(f"{path} is not valid JSON: {exc}") from exc
    machines = data.get("machines")
    if not isinstance(machines, dict):
        raise LockFileError(f"{path} is missing an object 'machines' key")
    return machines


def render_lock(registry: Registry) -> dict[str, Any]:
    """The lock-file content a clean `registry` should have — used both to
    *write* `machine_hashes.lock` (regeneration tooling) and, implicitly,
    to compute expectations in `diff()`."""
    machines: dict[str, Any] = {}
    for key in registry.keys():
        chart = registry.get(key)
        version = chart.get("version")
        machines[key] = {
            "hash": registry.hash(key),
            "version": version if isinstance(version, int) else None,
        }
    return {"schema_version": LOCK_SCHEMA_VERSION, "machines": machines}


def diff(registry: Registry, locked: dict[str, dict[str, Any]]) -> list[DriftFinding]:
    """Compare every machine `registry` currently loads against `locked`.

    A machine present in `locked` but no longer in `registry` is NOT
    reported here (removing a machine is a separate, deliberate act with
    its own review, not a hash-drift finding) — `check_removed()` covers
    that case explicitly so the two failure classes stay distinguishable.

    A drifted machine is *covered* iff:
      1. its chart `version` increased strictly versus the locked
         `version` (a missing/None locked version counts as covered only
         if the current chart declares a `version` at all — MUST-12 requires
         an explicit bump, not an absent field staying absent), and
      2. `upcasters.has_upcaster(machine, locked_hash, current_hash)` is
         True (a golden-snapshot-tested upcaster is registered for exactly
         this hash transition).
    Both are required (MUST-12); either alone is MUSTNOT-09 territory.
    """
    findings: list[DriftFinding] = []
    for key in registry.keys():
        current_hash = registry.hash(key)
        entry = locked.get(key)
        if entry is None:
            continue  # new machine, nothing to diff against yet
        locked_hash = entry.get("hash")
        if not isinstance(locked_hash, str):
            raise LockFileError(f"lock entry for '{key}' is missing a string 'hash'")
        if locked_hash == current_hash:
            continue

        locked_version = entry.get("version")
        current_version = registry.get(key).get("version")
        locked_version = locked_version if isinstance(locked_version, int) else None
        current_version = current_version if isinstance(current_version, int) else None

        version_bumped = current_version is not None and (
            locked_version is None or current_version > locked_version
        )
        upcaster_registered = has_upcaster(key, locked_hash, current_hash)
        covered = version_bumped and upcaster_registered

        if covered:
            reason = "version bumped and upcaster registered"
        elif not version_bumped and not upcaster_registered:
            reason = "no version bump and no registered upcaster (MUST-12/MUSTNOT-09)"
        elif not version_bumped:
            reason = "upcaster registered but chart 'version' was not bumped (MUST-12)"
        else:
            reason = "chart 'version' bumped but no upcaster registered for this hash transition"

        findings.append(
            DriftFinding(
                machine=key,
                locked_hash=locked_hash,
                current_hash=current_hash,
                locked_version=locked_version,
                current_version=current_version,
                covered=covered,
                reason=reason,
            )
        )
    return findings


def check_removed(registry: Registry, locked: dict[str, dict[str, Any]]) -> list[str]:
    """Machine keys present in the lock file but no longer in `registry`."""
    return sorted(set(locked) - set(registry.keys()))
