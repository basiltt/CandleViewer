"""Shared data types for board-automation guards (E01-T07).

Deliberately GitHub-API-free: these are plain dataclasses so guard
``evaluate()`` functions can be unit-tested with hand-built fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Comment:
    """A single issue comment, as needed by the guards."""

    author_login: str
    body: str
    # True only when this comment's author independently holds repo write
    # access (verified via the collaborator-permission API, not merely
    # "is the ticket owner") -- see guard_qa_signoff's deviation check.
    author_has_write_access: bool = False
    # True when the write-access lookup above could not be completed (API
    # error); callers must treat this as fail-closed.
    write_access_check_failed: bool = False


@dataclass(frozen=True)
class Issue:
    """The subset of issue state the guards need to reach a decision."""

    number: int
    kind: str  # "Story" | "Bug" | "Task" | "Epic" | "Spike" | "Chore" | "Unlabeled"
    labels: frozenset[str]
    body: str
    owner_login: str
    actor_login: str = ""  # who triggered the current event


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
    # Non-None means "write this Kind value to the Projects v2 Kind field"
    # (kind-sync guard only; requires PROJECTS_PAT -- see gh_adapter).
    set_project_kind: str | None = None
