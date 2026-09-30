"""candleviewer.statechart.persistence — quiescent persist + drain journal (E50-T10).

Owns the shutdown path of every catalogue machine
(29-statechart-adoption-plan.md §1.3, CV-C23/C40/C41/C49'/C58/C65'):

    assert started + settled          (CV-C40, CV-C49'/C58)
    refuse + audit if context._fault  (MUST-01)
    drain_pending()  -> journal       (CV-C65', both lanes, priority first)
    get_persisted_snapshot()          (root only, CV-C41)
    seal(...)                         (HMAC envelope — E50-T49, injected)
    repo.write_snapshot(...)
    stop()

`drain_pending()` is called only here (CV-LINT-DRAIN). Restore + HMAC
(`open_sealed`, `from_snapshot`) is E50-T49; this module exposes
`DrainJournal.replay_once()` which that restore calls after `start()`.

Storage and audit are injected Protocols: `statechart` may not import
`audit` or `storage` directly (import-linter, forbidden-M18), and the
Postgres tables (`machine_snapshots`, `machine_drain_journal`,
24-internal-schemas.md §17.6) land with migration E29-T12. An in-memory
journal ships here for tests and for the contract suite.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from xstate_statemachine import Interpreter
from xstate_statemachine.events import persist_event, restore_event

from candleviewer.statechart.config import SNAPSHOT_V

JournalLane = Literal["priority", "inbox"]


class PersistRefusedError(RuntimeError):
    """Raised when `persist()` refuses to write a snapshot (MUST-01)."""


@dataclass(frozen=True, slots=True)
class MachineKey:
    """Primary key of `machine_snapshots` / `machine_drain_journal`."""

    machine_kind: str
    entity_id: str
    env: str


@dataclass(frozen=True, slots=True)
class JournalEntry:
    """One drained event — mirrors a `machine_drain_journal` row."""

    send_id: str
    lane: JournalLane
    ordinal: int
    event_type: str
    record: dict[str, Any]
    receipt_error: str | None = None


@dataclass(frozen=True, slots=True)
class SealedSnapshot:
    """What `repo.write_snapshot` receives (the envelope E50-T49 seals)."""

    key: MachineKey
    version: int
    machine_hash: str
    snapshot: dict[str, Any]
    seal: Any


class SnapshotRepo(Protocol):
    async def write_snapshot(self, key: MachineKey, envelope: SealedSnapshot) -> None: ...


class PersistAudit(Protocol):
    async def drain_error(self, key: MachineKey, error: str) -> None: ...

    async def persist_refused(self, key: MachineKey, reason: str) -> None: ...


class DrainJournal(Protocol):
    async def append(self, key: MachineKey, entries: Sequence[JournalEntry]) -> None: ...

    async def replay_once(self, key: MachineKey, interp: Interpreter[Any]) -> int: ...


#: Seal callback: `(snapshot, machine_hash, version) -> seal` (E50-T49).
Sealer = Callable[[dict[str, Any], str, int], Awaitable[Any]]


def stable_send_id(key: MachineKey, ordinal: int, record: dict[str, Any]) -> str:
    """Deterministic de-dup key for a drained event (R11-W-1, R14-02).

    Same machine key + drain position + persisted record => same id, so a
    re-submitted journal append after a crash is idempotent.
    """
    canon = json.dumps(
        [key.machine_kind, key.entity_id, key.env, ordinal, record],
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:32]


def _is_settled(interp: Interpreter[Any]) -> bool:
    """CV-C40 / CV-C49': started, initial descent done, no macrostep open.

    Reads engine internals (`_descent_done`, `_step_in_flight`) because the
    pinned 0.9.1 exposes no public "settled after start" flag; this module
    is the one place allowed to couple to the runtime (CV-LINT-IMPORT).
    """
    descent = getattr(interp, "_descent_done", None)
    return (
        bool(interp.is_running)
        and descent is not None
        and bool(descent.is_set())
        and not interp._step_in_flight()
    )


class InMemoryDrainJournal:
    """Reference `DrainJournal` (tests, contract suite, dev).

    Semantics match `machine_drain_journal`: PK includes `send_id` (append is
    idempotent), rows are replayed in `ordinal` order (priority first) and
    stamped `replayed` so a second `replay_once` is a no-op (CV-C65').
    """

    def __init__(self) -> None:
        self._rows: dict[MachineKey, dict[str, JournalEntry]] = {}
        self._replayed: set[tuple[MachineKey, str]] = set()

    async def append(self, key: MachineKey, entries: Sequence[JournalEntry]) -> None:
        rows = self._rows.setdefault(key, {})
        for entry in entries:
            rows.setdefault(entry.send_id, entry)

    def rows(self, key: MachineKey) -> list[JournalEntry]:
        return sorted(self._rows.get(key, {}).values(), key=lambda e: e.ordinal)

    async def replay_once(self, key: MachineKey, interp: Interpreter[Any]) -> int:
        count = 0
        for entry in self.rows(key):
            marker = (key, entry.send_id)
            if marker in self._replayed:
                continue
            self._replayed.add(marker)
            ev = restore_event(entry.record)
            # Restore hook, not `send()`: keeps lane + engine provenance of
            # fired timers / completions (library #214), priority ahead of inbox.
            interp._enqueue_restored(ev, priority=entry.lane == "priority")
            count += 1
        return count


@dataclass(slots=True)
class Persister:
    """Wires `persist()` to its injected collaborators."""

    repo: SnapshotRepo
    journal: DrainJournal
    audit: PersistAudit
    seal: Sealer
    machine_hash_of: Callable[[str], str]
    version: int = field(default=SNAPSHOT_V)

    async def persist(self, interp: Interpreter[Any], *, key: MachineKey) -> None:
        """Quiescent persist (29 §1.3). See module docstring for the order."""
        if not _is_settled(interp):
            raise AssertionError(
                f"persist({key.machine_kind}/{key.entity_id}): interpreter is not "
                "started and settled (CV-C40, CV-C49'/C58); never persist an "
                "un-started or mid-step interpreter"
            )
        context = interp.context
        if isinstance(context, dict) and context.get("_fault") is not None:
            reason = "context carries _fault (MUST-01)"
            await self.audit.persist_refused(key, reason)
            raise PersistRefusedError(f"persist({key.machine_kind}/{key.entity_id}): {reason}")

        n_priority = len(interp._priority_queue)
        receipts = interp._receipts
        pending = list(interp.pending_events)
        waited = {id(ev) for ev in pending if id(ev) in receipts}
        drained = await interp.drain_pending()  # CV-LINT-DRAIN: only call site

        entries: list[JournalEntry] = []
        for ordinal, ev in enumerate(drained):
            lane: JournalLane = "priority" if ordinal < n_priority else "inbox"
            record = persist_event(ev, lane="priority" if lane == "priority" else None)
            receipt_error = "InterpreterStoppedError" if id(ev) in waited else None
            if receipt_error is not None:
                await self.audit.drain_error(key, receipt_error)  # R14-02
            entries.append(
                JournalEntry(
                    send_id=stable_send_id(key, ordinal, record),
                    lane=lane,
                    ordinal=ordinal,
                    event_type=str(ev.type),
                    record=record,
                    receipt_error=receipt_error,
                )
            )
        await self.journal.append(key, entries)

        blob = interp.get_persisted_snapshot()  # root only (CV-C41)
        machine_hash = self.machine_hash_of(key.machine_kind)
        seal = await self.seal(blob, machine_hash, self.version)
        await self.repo.write_snapshot(
            key,
            SealedSnapshot(
                key=key,
                version=self.version,
                machine_hash=machine_hash,
                snapshot=blob,
                seal=seal,
            ),
        )
        await interp.stop()
