"""Shared data types for board-automation guards (E01-T07).

Deliberately GitHub-API-free: these are plain dataclasses so guard
``evaluate()`` functions can be unit-tested with hand-built fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Comment:
    """A single issue comment, as needed by the guards."""

    author_login: str
    body: str
    author_is_team_member: bool = False


@dataclass(frozen=True)
class Issue:
    """The subset of issue state the guards need to reach a decision."""

    number: int
    kind: str  # "Story" | "Bug" | "Task" | "Epic" | "Spike" | "Chore"
    labels: frozenset[str]
    body: str
    owner_login: str
    actor_login: str = ""  # who triggered the current event
    always_security_areas: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class Decision:
    """The outcome of a guard's `evaluate()` call.

    ``allow=False`` means "block or reopen, per ADR-0017's detective-control
    design" -- the adapter decides the concrete GitHub call (reopen vs. leave
    open) based on the triggering event type.
    """

    allow: bool
    reason: str
    dod_ref: str
    audit_note: str
    guard: str
    fail_closed: bool = False
    add_labels: frozenset[str] = frozenset()
