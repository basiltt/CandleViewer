"""`RelationalRepository` — Postgres unit-of-work and session management.

E07-T01 ships only the base `UnitOfWork` and factory Protocol; aggregate
repositories (`UserRepository`, `AuditRepository`, ...) are created by their
owning epics (E09/E27/E29 etc., ticket "Out of scope") on top of this
contract, typically as attributes assembled inside a concrete
`RelationalRepository` implementation's `__aenter__`.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class UnitOfWork(Protocol):
    """One Postgres transaction boundary.

    Ordering/consistency guarantee: all repository calls made between
    `__aenter__` and a successful `commit()` are part of the same database
    transaction; `__aexit__` rolls back on any unhandled exception and is a
    no-op if `commit()` already ran. Never call `commit()` more than once per
    unit of work.
    """

    async def __aenter__(self) -> UnitOfWork: ...

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None: ...

    async def commit(self) -> None:
        """Commit the transaction. Raises if already committed or rolled back."""
        ...

    async def rollback(self) -> None:
        """Roll back the transaction explicitly (also happens implicitly on
        an unhandled exception inside the `async with` block)."""
        ...


@runtime_checkable
class RelationalRepository(Protocol):
    """Factory for `UnitOfWork`s against the Postgres relational tier.

    Aggregate-specific repositories are not part of this Protocol — each
    owning epic defines its own (e.g. `UserRepository`) and obtains a session
    from the `UnitOfWork` its implementation exposes. This keeps M10 from
    depending on every aggregate's schema (CONSTITUTION.md C-3.1: M10 depends
    only on M1).
    """

    def unit_of_work(self) -> UnitOfWork:
        """Start a new `UnitOfWork` (call `async with` on the result)."""
        ...
